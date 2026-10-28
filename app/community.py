"""粉絲功能（要用 Google 帳號登入）：

- 去過的場次（我的足跡，含統計）、喜歡的歌
- 首頁跑馬燈：送出就顯示，後台可以隱藏、封鎖
- 補充演出資訊與歌單、投稿樂譜：先進待審清單，後台核准才上線（審核頁在 admin.py）
- 公開個人頁 /fans/<handle>/（使用者自己選要不要開）

登入流程與帳號資料在 visitors.py。會寫入的請求一律 POST，並檢查 Origin 是不是本站。
"""
import io
import json
import math
import os
import re
import secrets
from collections import Counter, defaultdict
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import db, i18n, queries as Q, taiwan, visitors as V
from .admin import same_origin
from .web import current_visitor, get_con, lang_of, render

router = APIRouter()

SHEET_MAX_FILES = 8
SHEET_MAX_BYTES = 10 * 1024 * 1024
SHEET_MAX_SIDE = 2400


class NeedLogin(Exception):
    pass


def safe_next(value, default="/me/"):
    """登入後要回去的網址：只接受站內路徑，擋掉 //evil.com 這種。"""
    value = value or ""
    return value if value.startswith("/") and not value.startswith("//") else default


def login_url(request, next_url=None):
    nxt = next_url or (request.url.path if lang_of(request) == "zh" else "/en" + request.url.path)
    return "/auth/login?next=" + quote(nxt)


def visitor_or_none(request, con):
    return current_visitor(request, con)


def check_post(request):
    if not same_origin(request):
        raise HTTPException(403, "表單來源不是本站")


def T(request, key, **kw):
    return i18n.t(lang_of(request), key, **kw)


# ==================================================================== 預設頁面
PRIVACY_ZH = """<h2>我們存了什麼</h2>
<p>用 Google 帳號登入時，我們只會從 Google 取得：帳號 ID、email、名字、大頭貼。email 只用來辨識帳號，不會公開、不會寄信給你。</p>
<p>你在網站上記錄的「去過的場次」「喜歡的歌」、投稿的跑馬燈、演出補充與樂譜，會跟你的帳號一起存在本站的資料庫。</p>
<h2>誰看得到</h2>
<p>去過的場次與喜歡的歌預設只有你自己看得到；網站只會顯示匿名的加總（例如「12 位粉絲去過這場」）。你可以在「我的 → 設定」開啟公開個人頁。</p>
<p>跑馬燈與樂譜的署名由你每次投稿時選擇：Google 帳號名、自選暱稱或匿名。</p>
<h2>刪除帳號</h2>
<p>在「我的 → 設定」可以刪除帳號，所有紀錄與投稿會一起刪除（已經被核准、套用到演出資料的補充除外）。</p>
<h2>樂譜</h2>
<p>網站上的樂譜皆為粉絲自行採譜，非官方版本。權利人如需下架，請來信，我們會盡快處理。</p>"""

PRIVACY_EN = """<h2>What we store</h2>
<p>When you sign in with Google we only receive your account ID, email, name and profile picture. Your email is used to identify your account; it is never shown publicly and we never email you.</p>
<p>The shows you attended, songs you like, and anything you submit (ticker messages, show details, sheet music) are stored with your account.</p>
<h2>Who can see it</h2>
<p>Your shows and liked songs are private by default; the site only shows anonymous totals (e.g. "12 fans were there"). You can turn on a public profile in My page → Settings.</p>
<p>For ticker messages and sheet music you choose the name each time: your Google name, your nickname, or anonymous.</p>
<h2>Deleting your account</h2>
<p>You can delete your account in My page → Settings. All your records and submissions are deleted with it (except corrections already applied to show data).</p>
<h2>Sheet music</h2>
<p>All sheet music on this site is transcribed by fans and is not official. Rights holders can email us to have it taken down.</p>"""


def ensure_default_pages(con):
    """隱私權政策頁（Google 登入的同意畫面要填它的網址）。已經有了就不動，內容可以在後台改。"""
    if not con.execute("SELECT 1 FROM pages WHERE slug = 'privacy'").fetchone():
        con.execute("INSERT INTO pages (kind, slug, title, title_en, body_html, body_html_en, published, sort_order, "
                    "updated_at) VALUES ('page', 'privacy', '隱私權政策', 'Privacy Policy', ?, ?, 1, 99, ?)",
                    (PRIVACY_ZH, PRIVACY_EN, db.now()))
        con.commit()


# ==================================================================== 登入、登出
def redirect_uri(request):
    """Google 登入完要回來的網址。要跟 Google Cloud Console 裡登記的一字不差。
    Azure 前面有一層代理，真正的網址在 X-Forwarded-* 標頭裡。"""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return "%s://%s/auth/google/callback" % (scheme, host)


def finish_login(request, con, visitor_id, nxt):
    token = V.create_session(con, visitor_id)
    resp = RedirectResponse(safe_next(nxt), status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(V.COOKIE, token, httponly=True, samesite="lax", secure=https, max_age=V.SESSION_DAYS * 86400, path="/")
    resp.delete_cookie(V.STATE_COOKIE, path="/")
    return resp


@router.get("/auth/login")
def login_page(request: Request, con=Depends(get_con)):
    nxt = safe_next(request.query_params.get("next"))
    if current_visitor(request, con):
        return RedirectResponse(nxt, status_code=303)
    return render(request, con, "login.html", {"next": nxt, "google": V.google_enabled(), "dev_login": V.DEV_LOGIN,
                                               "error": request.query_params.get("error")},
                  page={"title": "登入", "title_en": "Sign in"})


@router.get("/auth/google/login")
def google_login(request: Request):
    if not V.google_enabled():
        raise HTTPException(404)
    state, verifier, challenge = V.start_login()
    nxt = safe_next(request.query_params.get("next"))
    resp = RedirectResponse(V.google_auth_url(state, challenge, redirect_uri(request)), status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    # state、verifier、登入後要回去的網址，10 分鐘內有效
    resp.set_cookie(V.STATE_COOKIE, json.dumps([state, verifier, nxt]), httponly=True, samesite="lax", secure=https,
                    max_age=600, path="/")
    return resp


@router.get("/auth/google/callback")
def google_callback(request: Request, con=Depends(get_con)):
    def fail(msg):
        return RedirectResponse("/auth/login?error=" + quote(msg), status_code=303)
    if request.query_params.get("error"):
        return fail("你取消了 Google 登入。")
    try:
        state, verifier, nxt = json.loads(request.cookies.get(V.STATE_COOKIE) or "")
    except (ValueError, TypeError):
        return fail("登入逾時，請再試一次。")
    if not secrets.compare_digest(state, request.query_params.get("state") or ""):
        return fail("登入驗證失敗，請再試一次。")
    try:
        claims = V.google_exchange(request.query_params.get("code") or "", verifier, redirect_uri(request))
    except V.LoginError as e:
        return fail(str(e))
    visitor_id = V.upsert_visitor(con, "google:" + claims["sub"], claims.get("email", ""),
                                  claims.get("name", ""), claims.get("picture", ""))
    return finish_login(request, con, visitor_id, nxt)


@router.post("/auth/dev-login")
async def dev_login(request: Request, con=Depends(get_con)):
    """本機開發用：輸入名字就登入。只有 DEV_LOGIN=1 而且不在 Azure 上才有。"""
    if not V.DEV_LOGIN:
        raise HTTPException(404)
    check_post(request)
    form = await request.form()
    name = (form.get("name") or "").strip()[:40] or "測試粉絲"
    visitor_id = V.upsert_visitor(con, "dev:" + name, "", name, "")
    return finish_login(request, con, visitor_id, form.get("next"))


@router.post("/auth/logout")
def logout(request: Request, con=Depends(get_con)):
    check_post(request)
    V.end_session(con, request.cookies.get(V.COOKIE))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(V.COOKIE, path="/")
    return resp


# ==================================================================== 我的足跡（統計）
def footprint(con, lang, visitor_id):
    perfs = [dict(r) for r in con.execute(
        Q.PERF_SELECT + " JOIN attendance a ON a.performance_id = p.id AND a.visitor_id = ? ORDER BY p.event_date DESC",
        (visitor_id,))]
    types = Q.event_types(con)
    by_year = Counter(p["event_date"][:4] for p in perfs)
    years = sorted(by_year)
    by_type = Counter(p["event_type_id"] for p in perfs)
    type_rows = [(i, t) for i, t in enumerate(types) if by_type.get(t["id"])]

    # 地圖：跟演出頁同一張，只是圓點大小換成「我去過幾場」
    city_n = Counter(p["city_id"] for p in perfs)
    top = max(city_n.values() or [1])
    map_cities = [dict(c, n=city_n.get(c["id"], 0),
                       r=round(4 + 9 * math.sqrt(city_n[c["id"]] / top), 1) if city_n.get(c["id"]) else 3)
                  for c in Q.cities(con)]

    # 現場聽過的歌：去過的（已發生的）場次 × 歌單
    past_ids = [p["id"] for p in perfs if p["event_date"] <= Q.today()]
    heard, info = Counter(), {}
    for items in Q.setlists(con, past_ids).values():
        for it in items:
            key = ("s", it["song_id"]) if it["song_id"] else ("c", it["custom_title"])
            heard[key] += 1
            info[key] = it
    heard_rows = [{"title": Q.song_title(lang, info[k]), "count": n, "lyrics_slug": info[k]["lyrics_slug"]}
                  for k, n in heard.most_common()]
    heard_song_ids = {k[1] for k in heard if k[0] == "s"}
    # 還沒在現場聽過的：163braces 自己的歌（沒有填原唱的）而且有歌詞
    never = [s for s in con.execute(Q.SONG_SELECT + " WHERE g.artist = '' AND l.published = 1 ORDER BY g.sort_order")
             if s["id"] not in heard_song_ids]

    return {
        "performances": perfs,
        "total": len(perfs),
        "past": len(past_ids),
        "first": perfs[-1]["event_date"] if perfs else None,
        "heard": heard_rows,
        "distinct_songs": len(heard),
        "never": never,
        "map_cities": map_cities,
        "charts": {
            "years": {"labels": years, "datasets": [{"label": i18n.t(lang, "shows"), "data": [by_year[y] for y in years],
                                                     "backgroundColor": Q.color(0)}]},
            "types": {"labels": [i18n.tr(lang, t, "name") for _, t in type_rows],
                      "datasets": [{"data": [by_type[t["id"]] for _, t in type_rows],
                                    "backgroundColor": [Q.color(i) for i, _ in type_rows]}]},
        },
    }


def liked_songs(con, visitor_id):
    return con.execute(Q.SONG_SELECT + " JOIN song_likes k ON k.song_id = g.id AND k.visitor_id = ? "
                       "ORDER BY k.created_at DESC", (visitor_id,)).fetchall()


def my_submissions(con, visitor_id):
    contribs = con.execute("SELECT c.*, p.event_date, p.event_name FROM contributions c "
                           "JOIN performances p ON p.id = c.performance_id WHERE c.visitor_id = ? "
                           "ORDER BY c.created_at DESC", (visitor_id,)).fetchall()
    sheets = con.execute("SELECT s.*, g.title AS song_title FROM sheets s JOIN songs g ON g.id = s.song_id "
                         "WHERE s.visitor_id = ? ORDER BY s.created_at DESC", (visitor_id,)).fetchall()
    marquee = con.execute("SELECT * FROM marquee_posts WHERE visitor_id = ? ORDER BY created_at DESC LIMIT 20",
                          (visitor_id,)).fetchall()
    return {"contributions": contribs, "sheets": sheets, "marquee": marquee}


ME_TABS = ("footprint", "likes", "submissions", "settings")


@router.get("/me/")
def me_page(request: Request, con=Depends(get_con)):
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    lang = lang_of(request)
    tab = request.query_params.get("tab") if request.query_params.get("tab") in ME_TABS else "footprint"
    return render(request, con, "me.html", {
        "tab": tab, "fp": footprint(con, lang, visitor["id"]), "likes": liked_songs(con, visitor["id"]),
        "subs": my_submissions(con, visitor["id"]), "map": taiwan.map_data(), "msg": request.query_params.get("msg"),
    }, page={"title": "我的", "title_en": "My page"})


@router.post("/me/settings")
async def me_settings(request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    form = await request.form()
    back = ("/en" if lang_of(request) == "en" else "") + "/me/?tab=settings"
    nickname = (form.get("nickname") or "").strip()[:30]
    public = 1 if form.get("profile_public") else 0
    handle = (form.get("handle") or "").strip()
    try:
        handle = V.check_handle(handle) if handle else None
        if public and not handle:
            raise V.LoginError("要公開個人頁，請先設定個人頁網址。")
        con.execute("UPDATE visitors SET nickname = ?, handle = ?, profile_public = ? WHERE id = ?",
                    (nickname, handle, public, visitor["id"]))
        con.commit()
    except V.LoginError as e:
        return RedirectResponse(back + "&msg=" + quote(str(e)), status_code=303)
    except Exception:
        return RedirectResponse(back + "&msg=" + quote("這個個人頁網址已經有人用了，換一個試試。"), status_code=303)
    return RedirectResponse(back + "&msg=" + quote(T(request, "saved")), status_code=303)


@router.post("/me/delete")
async def me_delete(request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    form = await request.form()
    if not visitor or form.get("confirm") != "DELETE":
        return RedirectResponse("/me/?tab=settings&msg=" + quote("請在確認欄輸入 DELETE。"), status_code=303)
    V.delete_visitor(con, visitor["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(V.COOKIE, path="/")
    return resp


@router.get("/fans/{handle}/")
def public_profile(handle: str, request: Request, con=Depends(get_con)):
    row = con.execute("SELECT * FROM visitors WHERE handle = ? AND profile_public = 1 AND banned = 0",
                      (handle.lower(),)).fetchone()
    if not row:
        raise HTTPException(404)
    lang = lang_of(request)
    name = row["nickname"] or i18n.t(lang, "fan")
    return render(request, con, "fan.html", {
        "fan": row, "fan_name": name, "fp": footprint(con, lang, row["id"]), "likes": liked_songs(con, row["id"]),
        "map": taiwan.map_data(),
    }, page={"title": name, "title_en": name})


# ==================================================================== 去過、喜歡（按鈕用的 API）
def need_login_json(request):
    return JSONResponse({"error": "login", "login_url": login_url(request, request.headers.get("x-return-to"))},
                        status_code=401)


@router.post("/api/me/attendance/{performance_id:int}")
def toggle_attendance(performance_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    if not con.execute("SELECT 1 FROM performances WHERE id = ?", (performance_id,)).fetchone():
        raise HTTPException(404)
    key = (visitor["id"], performance_id)
    if con.execute("SELECT 1 FROM attendance WHERE visitor_id = ? AND performance_id = ?", key).fetchone():
        con.execute("DELETE FROM attendance WHERE visitor_id = ? AND performance_id = ?", key)
        on = False
    else:
        con.execute("INSERT INTO attendance VALUES (?, ?, ?)", key + (db.now(),))
        on = True
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM attendance WHERE performance_id = ?", (performance_id,)).fetchone()[0]
    return {"on": on, "count": n}


@router.post("/api/me/likes/{song_id:int}")
def toggle_like(song_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    if not con.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone():
        raise HTTPException(404)
    key = (visitor["id"], song_id)
    if con.execute("SELECT 1 FROM song_likes WHERE visitor_id = ? AND song_id = ?", key).fetchone():
        con.execute("DELETE FROM song_likes WHERE visitor_id = ? AND song_id = ?", key)
        on = False
    else:
        con.execute("INSERT INTO song_likes VALUES (?, ?, ?)", key + (db.now(),))
        on = True
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM song_likes WHERE song_id = ?", (song_id,)).fetchone()[0]
    return {"on": on, "count": n}


def attended_ids(con, visitor):
    if not visitor:
        return set()
    return {r[0] for r in con.execute("SELECT performance_id FROM attendance WHERE visitor_id = ?", (visitor["id"],))}


def attendance_counts(con):
    return {r[0]: r[1] for r in con.execute("SELECT performance_id, COUNT(*) FROM attendance GROUP BY performance_id")}


def like_state(con, visitor, song_id):
    n = con.execute("SELECT COUNT(*) FROM song_likes WHERE song_id = ?", (song_id,)).fetchone()[0]
    on = bool(visitor and con.execute("SELECT 1 FROM song_likes WHERE visitor_id = ? AND song_id = ?",
                                      (visitor["id"], song_id)).fetchone())
    return {"on": on, "count": n}


# ==================================================================== 跑馬燈
def marquee_items(con, lang, limit=30):
    rows = con.execute("SELECT m.*, v.google_name, v.nickname FROM marquee_posts m JOIN visitors v ON v.id = m.visitor_id "
                       "WHERE m.hidden = 0 AND v.banned = 0 ORDER BY m.created_at DESC LIMIT ?", (limit,)).fetchall()
    anon = i18n.t(lang, "anonymous")
    return [{"text": r["text"], "name": V.display_name(r, r["name_mode"], anon)} for r in rows]


@router.post("/api/marquee")
async def post_marquee(request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    form = await request.form()
    text = " ".join((form.get("text") or "").split())         # 換行、連續空白收成一個空白
    mode = form.get("name_mode") if form.get("name_mode") in V.NAME_MODES else "nickname"
    units = V.text_units(text)
    if visitor["banned"]:
        error = T(request, "banned")
    elif not text or not units:
        error = T(request, "marquee_empty")
    elif units > V.MARQUEE_MAX_UNITS or len(text) > V.MARQUEE_MAX_CHARS:
        error = T(request, "marquee_too_long", n=V.MARQUEE_MAX_UNITS)
    elif V.over_daily_limit(con, "marquee", visitor["id"]):
        error = T(request, "daily_limit", n=V.DAILY_LIMITS["marquee"])
    else:
        con.execute("INSERT INTO marquee_posts (visitor_id, text, name_mode, created_at) VALUES (?, ?, ?, ?)",
                    (visitor["id"], text, mode, db.now()))
        con.commit()
        return {"ok": True}
    return JSONResponse({"ok": False, "error": error}, status_code=400)


# ==================================================================== 補充演出資訊與歌單
INFO_FIELDS = ("event_name", "event_name_en", "venue", "venue_en")


def parse_setlist_text(con, text):
    """一行一首，「曲名｜備註」。曲名跟曲庫一樣（中文或英文）就對到那首歌，其他當自訂曲名。"""
    titles = {}
    for s in con.execute("SELECT id, title, title_en FROM songs ORDER BY sort_order"):
        for t in (s["title"], s["title_en"]):
            if t:
                titles.setdefault(t.strip().lower(), s["id"])
    items = []
    for line in (text or "").splitlines():
        parts = line.replace("|", "｜").split("｜", 1)
        # 去掉行首的「1.」「2、」「3)」這種編號；只有數字的曲名（例如 632164873428077）不能被吃掉
        title = re.sub(r"^\d{1,3}\s*[.、)）]\s*", "", parts[0].strip())
        if not title:
            continue
        song_id = titles.get(title.lower())
        items.append({"song_id": song_id, "custom_title": "" if song_id else title[:120],
                      "note": (parts[1].strip() if len(parts) > 1 else "")[:120]})
    return items


def setlist_text(con, performance_id):
    rows = con.execute("SELECT s.custom_title, s.note, g.title FROM setlist_items s LEFT JOIN songs g ON g.id = s.song_id "
                       "WHERE s.performance_id = ? ORDER BY s.position, s.id", (performance_id,)).fetchall()
    return "\n".join((r["title"] or r["custom_title"]) + ("｜" + r["note"] if r["note"] else "") for r in rows)


@router.get("/contribute/performance/{performance_id:int}/")
def contribute_performance_form(performance_id: int, request: Request, con=Depends(get_con)):
    perf = con.execute(Q.PERF_SELECT + " WHERE p.id = ?", (performance_id,)).fetchone() or _404()
    visitor = current_visitor(request, con)
    return render(request, con, "contribute_performance.html", {
        "perf": perf, "setlist_text": setlist_text(con, performance_id), "error": request.query_params.get("error"),
        "need_login": not visitor,
    }, page={"title": "補充演出資訊", "title_en": "Suggest an edit"})


@router.post("/contribute/performance/{performance_id:int}/")
async def contribute_performance(performance_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    perf = con.execute("SELECT * FROM performances WHERE id = ?", (performance_id,)).fetchone() or _404()
    form = await request.form()
    back = request.url.path

    def fail(key):
        return RedirectResponse(back + "?error=" + quote(T(request, key)), status_code=303)
    if visitor["banned"]:
        return fail("banned")
    payload = {}
    for f in INFO_FIELDS:
        value = (form.get(f) or "").strip()[:255]
        if value != perf[f]:
            payload[f] = value
    new_setlist = (form.get("setlist") or "").strip()
    if new_setlist != setlist_text(con, performance_id).strip():
        payload["setlist"] = parse_setlist_text(con, new_setlist)
    if not payload:
        return fail("contribute_nothing")
    source = (form.get("source") or "").strip()[:500]
    if not source:
        return fail("contribute_need_source")
    if V.over_daily_limit(con, "contribution", visitor["id"]):
        return RedirectResponse(back + "?error=" + quote(T(request, "daily_limit", n=V.DAILY_LIMITS["contribution"])),
                                status_code=303)
    payload["source"] = source
    payload["message"] = (form.get("message") or "").strip()[:1000]
    con.execute("INSERT INTO contributions (visitor_id, performance_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (visitor["id"], performance_id, json.dumps(payload, ensure_ascii=False), db.now()))
    con.commit()
    me = ("/en" if lang_of(request) == "en" else "") + "/me/?tab=submissions&msg=" + quote(T(request, "contribute_thanks"))
    return RedirectResponse(me, status_code=303)


def _404():
    raise HTTPException(404)


# ==================================================================== 樂譜
def sheets_for_songs(con, lang, song_ids, statuses=("approved",)):
    if not song_ids:
        return []
    rows = con.execute(
        "SELECT s.*, v.google_name, v.nickname, g.title AS song_title FROM sheets s "
        "LEFT JOIN visitors v ON v.id = s.visitor_id JOIN songs g ON g.id = s.song_id "
        "WHERE s.song_id IN (%s) AND s.status IN (%s) ORDER BY s.created_at"
        % (",".join("?" * len(song_ids)), ",".join("?" * len(statuses))), list(song_ids) + list(statuses)).fetchall()
    files = defaultdict(list)
    for f in con.execute("SELECT * FROM sheet_files WHERE sheet_id IN (%s) ORDER BY position"
                         % ",".join("?" * len(rows)), [r["id"] for r in rows]) if rows else []:
        files[f["sheet_id"]].append(f)
    anon = i18n.t(lang, "anonymous")
    out = []
    for r in rows:
        name = V.display_name(r, r["name_mode"], anon) if r["google_name"] is not None else anon
        out.append(dict(r, author=name, files=files.get(r["id"], [])))
    return out


def store_sheet_image(upload):
    """樂譜圖檔：重新編碼成 JPEG（去掉照片裡的 GPS、拍攝資訊），最長邊縮到 2400px。"""
    from PIL import Image, ImageOps
    raw = upload.file.read(SHEET_MAX_BYTES + 1)
    if len(raw) > SHEET_MAX_BYTES:
        raise ValueError("toolarge")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("format")
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, "white")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((SHEET_MAX_SIDE, SHEET_MAX_SIDE), Image.LANCZOS)
            name = "sheets/%s.jpg" % secrets.token_hex(12)
            path = os.path.join(db.MEDIA_ROOT, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            im.save(path, format="JPEG", quality=88)
            return name, im.width, im.height
    except ValueError:
        raise
    except Exception:
        raise ValueError("format")


@router.get("/contribute/sheet/{song_id:int}/")
def contribute_sheet_form(song_id: int, request: Request, con=Depends(get_con)):
    song = con.execute(Q.SONG_SELECT + " WHERE g.id = ?", (song_id,)).fetchone() or _404()
    return render(request, con, "contribute_sheet.html", {
        "song": song, "error": request.query_params.get("error"), "need_login": not current_visitor(request, con),
        "max_files": SHEET_MAX_FILES, "contact_email": db.get_setting(con, "contact_email"),
    }, page={"title": "投稿樂譜", "title_en": "Submit sheet music"})


@router.post("/contribute/sheet/{song_id:int}/")
async def contribute_sheet(song_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone() or _404()
    form = await request.form()
    back = request.url.path

    def fail(key, **kw):
        return RedirectResponse(back + "?error=" + quote(T(request, key, **kw)), status_code=303)
    if visitor["banned"]:
        return fail("banned")
    title = (form.get("title") or "").strip()[:80]
    text_body = (form.get("text_body") or "").strip()[:20000]
    video = (form.get("video_url") or "").strip()[:500]
    uploads = [u for u in form.getlist("files") if getattr(u, "filename", "")]
    if not form.get("own_work"):
        return fail("sheet_need_own")
    if not title:
        return fail("sheet_need_title")
    if not uploads and not text_body:
        return fail("sheet_need_content")
    if len(uploads) > SHEET_MAX_FILES:
        return fail("sheet_too_many", n=SHEET_MAX_FILES)
    if video and urlparse(video).scheme not in ("http", "https"):
        return fail("sheet_bad_video")
    if V.over_daily_limit(con, "sheet", visitor["id"]):
        return fail("daily_limit", n=V.DAILY_LIMITS["sheet"])
    stored = []
    try:
        for u in uploads:
            stored.append(store_sheet_image(u))
    except ValueError as e:
        for name, _, _ in stored:                       # 有一張不行就全部不收，已經存的刪掉
            os.remove(os.path.join(db.MEDIA_ROOT, name))
        return fail("sheet_file_too_large" if str(e) == "toolarge" else "sheet_bad_file")
    mode = form.get("name_mode") if form.get("name_mode") in V.NAME_MODES else "nickname"
    sheet_id = con.execute("INSERT INTO sheets (visitor_id, song_id, title, text_body, video_url, name_mode, created_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (visitor["id"], song_id, title, text_body, video, mode, db.now())).lastrowid
    con.executemany("INSERT INTO sheet_files (sheet_id, position, file, width, height) VALUES (?, ?, ?, ?, ?)",
                    [(sheet_id, i, name, w, h) for i, (name, w, h) in enumerate(stored)])
    con.commit()
    me = ("/en" if lang_of(request) == "en" else "") + "/me/?tab=submissions&msg=" + quote(T(request, "sheet_thanks"))
    return RedirectResponse(me, status_code=303)
