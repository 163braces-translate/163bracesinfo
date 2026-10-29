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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.datastructures import QueryParams

from . import db, i18n, queries as Q, taiwan, visitors as V
from .admin import same_origin
from .web import current_visitor, get_con, lang_of, render

router = APIRouter()

SHEET_MAX_FILES = 8
SHEET_MAX_BYTES = 5 * 1024 * 1024
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
<p>「回顧」與「我的足跡」裡選的住的地方（行政區），預設只記在你的瀏覽器；勾選「記在我的帳號」才會存到本站，取消勾選就會刪除。</p>
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
<p>The district you pick as where you live (in Recap and My shows) stays in your browser unless you tick "Remember on my account"; untick it to delete it from the site.</p>
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


def finish_login(request, con, visitor_id, nxt, max_age=V.SESSION_DAYS * 86400):
    token = V.create_session(con, visitor_id)
    resp = RedirectResponse(safe_next(nxt), status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(V.COOKIE, token, httponly=True, samesite="lax", secure=https, max_age=max_age, path="/")
    resp.delete_cookie(V.STATE_COOKIE, path="/")
    return resp


@router.get("/auth/login")
def login_page(request: Request, con=Depends(get_con)):
    nxt = safe_next(request.query_params.get("next"))
    visitor = current_visitor(request, con)
    if visitor and not V.is_guest(visitor):             # 訪客可以再來這裡改用 Google 登入
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


@router.post("/auth/guest-login")
async def guest_login(request: Request, con=Depends(get_con)):
    """訪客登入：自取暱稱，開一個 24 小時的臨時帳號（見 visitors.is_guest）。"""
    check_post(request)
    form = await request.form()
    nickname = " ".join((form.get("nickname") or "").split())[:30]
    if not nickname:
        return RedirectResponse("/auth/login?error=" + quote(T(request, "guest_need_nickname")) +
                                "&next=" + quote(safe_next(form.get("next"))), status_code=303)
    stamp = db.now()
    visitor_id = con.execute("INSERT INTO visitors (google_sub, google_name, nickname, created_at, last_login) "
                             "VALUES (?, ?, ?, ?, ?)",
                             ("guest:" + secrets.token_hex(12), nickname, nickname, stamp, stamp)).lastrowid
    return finish_login(request, con, visitor_id, form.get("next"), max_age=V.GUEST_HOURS * 3600)


# 網站上的總數（幾位粉絲去過、愛心數、樂譜的讚）不算訪客：訪客的紀錄只在他自己的「我的」裡有意義
COUNTED = "visitor_id NOT IN (SELECT id FROM visitors WHERE google_sub LIKE 'guest:%')"


def submit_block(request, visitor):
    """不能投稿的原因（停權、訪客），可以的話回傳 None。"""
    if visitor["banned"]:
        return T(request, "banned")
    if V.is_guest(visitor):
        return T(request, "guest_cannot_submit")
    return None


@router.post("/auth/logout")
def logout(request: Request, con=Depends(get_con)):
    check_post(request)
    V.end_session(con, request.cookies.get(V.COOKIE))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(V.COOKIE, path="/")
    return resp


# ==================================================================== 我的足跡（統計）
def footprint_filters(params):
    """我的足跡的篩選：跟演出頁一樣（關鍵字、類型、城市、日期），另外可以直接選整年（year=2025 → 1/1～12/31）。"""
    f = Q.parse_filters(params)
    year = params.get("year") or ""
    # 有填日期就以日期為準（選了整年之後又改成自訂期間）；只有 year 沒有日期時（沒有 JavaScript）才換算
    if len(year) == 4 and year.isdigit() and not (f["date_from"] or f["date_to"]):
        f.update(date_filter_type="range", date_from=year + "-01-01", date_to=year + "-12-31")
    return f


def footprint(con, lang, visitor_id, f=None):
    attended = con.execute("SELECT p.event_date, p.city_id, p.event_type_id FROM performances p "
                           "JOIN attendance a ON a.performance_id = p.id AND a.visitor_id = ?", (visitor_id,)).fetchall()
    f = f or footprint_filters(QueryParams(""))
    where, args = Q._where(f)
    perfs = [dict(r) for r in con.execute(
        Q.PERF_SELECT + " JOIN attendance a ON a.performance_id = p.id AND a.visitor_id = ?" + where +
        " ORDER BY p.event_date DESC", [visitor_id] + args)]
    types = Q.event_types(con)
    # 篩選選單只列出去過的年份、類型、城市；整年的話標出是哪一年
    whole_year = (f["date_filter_type"] == "range" and f["date_from"][:4] == f["date_to"][:4]
                  and f["date_from"][4:] == "-01-01" and f["date_to"][4:] == "-12-31")
    options = {
        "years": sorted({r["event_date"][:4] for r in attended}, reverse=True),
        "types": [t for t in types if t["id"] in {r["event_type_id"] for r in attended}],
        "cities": [c for c in Q.cities(con) if c["id"] in {r["city_id"] for r in attended}],
        "year": f["date_from"][:4] if whole_year else "",
    }
    by_year = Counter(p["event_date"][:4] for p in perfs)
    years = sorted(by_year)
    by_type = Counter(p["event_type_id"] for p in perfs)
    # 甜甜圈從 12 點鐘順時針、多的在前，一樣多的照後台的排序；顏色跟著類型走（i 是類型的順序），換順序顏色也不會跳
    type_rows = sorted([(i, t) for i, t in enumerate(types) if by_type.get(t["id"])], key=lambda x: (-by_type[x[1]["id"]], x[0]))

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
        "f": f, "options": options, "any": bool(attended),
        "filtered": any([f["q"], f["city"], f["event_type"], f["date_from"], f["date_to"]]),
        "performances": perfs,
        "total": len(perfs),
        "past": len(past_ids),
        "first": perfs[-1]["event_date"] if perfs else None,
        "heard": heard_rows,
        "distinct_songs": len(heard),
        "never": never,
        "map_cities": map_cities,
        # 移動路線（只在自己的「我的足跡」畫，住的地方在瀏覽器裡選）：已經去過的場次，照日期排
        "route": {"cities": route_cities(con, lang), "shows": [
            {"d": p["event_date"], "c": p["city_id"], "ll": [p["lng"], p["lat"]] if p["lat"] is not None else None,
             "label": "%s · %s · %s" % (p["event_date"].replace("-", "/"), i18n.tr(lang, p, "event_name"),
                                        i18n.tr(lang, p, "venue") or i18n.tr(lang, p, "city_name"))}
            for p in sorted(perfs, key=lambda p: (p["event_date"], p["id"])) if p["event_date"] <= Q.today()]},
        "charts": {
            # 每年去了幾場：依演出類型堆疊，顏色跟甜甜圈一樣（跟著類型走）
            "years": {"labels": years, "datasets": [
                {"label": i18n.tr(lang, t, "name"), "backgroundColor": Q.color(i),
                 "data": [sum(1 for p in perfs if p["event_date"][:4] == y and p["event_type_id"] == t["id"]) for y in years]}
                for i, t in type_rows]},
            "types": {"labels": [i18n.tr(lang, t, "name") for _, t in type_rows],
                      "datasets": [{"data": [by_type[t["id"]] for _, t in type_rows],
                                    "backgroundColor": [Q.color(i) for i, _ in type_rows]}]},
        },
    }


def route_cities(con, lang):
    """移動路線用的城市：地圖上的代號、中心點（場地還沒填座標時用；static/home-route.js）。"""
    return [{"id": c["id"], "name": i18n.tr(lang, c, "name"), "key": c["map_key"], "ll": taiwan.lonlat(c["map_key"])}
            for c in Q.cities(con)]


def recap_data(con, lang, visitor):
    """「回顧」分頁的資料：去過的（已經發生的）場次、各場歌單、喜歡的歌、地圖。
    期間、圖表、移動距離都在瀏覽器裡算（static/recap.js），選了什麼不會送回來。"""
    perfs = con.execute("SELECT p.id, p.event_date, p.event_type_id, p.city_id, p.lat, p.lng FROM performances p "
                        "JOIN attendance a ON a.performance_id = p.id AND a.visitor_id = ? "
                        "WHERE p.event_date <= ? ORDER BY p.event_date, p.id", (visitor["id"], Q.today())).fetchall()
    titles, shows = {}, []
    lists = Q.setlists(con, [p["id"] for p in perfs])
    for p in perfs:
        keys = []
        for it in lists.get(p["id"], []):
            key = "s%d" % it["song_id"] if it["song_id"] else "c:" + it["custom_title"]
            titles[key] = Q.song_title(lang, it)
            keys.append(key)
        shows.append({"d": p["event_date"], "t": p["event_type_id"], "c": p["city_id"], "songs": keys,
                      "ll": [p["lng"], p["lat"]] if p["lat"] is not None else None})     # 場地座標；沒有的話用縣市中心
    logo = db.get_setting(con, "replay_logo_id")
    return {
        "shows": shows, "titles": titles, "today": Q.today(),
        "types": [{"id": t["id"], "name": i18n.tr(lang, t, "name"), "color": Q.color(i)}
                  for i, t in enumerate(Q.event_types(con))],
        "cities": route_cities(con, lang),
        "likes": [i18n.tr(lang, s, "title") for s in liked_songs(con, visitor["id"])],
        "names": {"google": "" if V.is_guest(visitor) else visitor["google_name"], "nickname": visitor["nickname"]},
        "home_saved": visitor["home_district"], "can_save_home": not V.is_guest(visitor),
        "map": taiwan.map_data(), "colors": Q.CHART_COLORS, "other_color": Q.OTHER_COLOR,
        "logo": Q.image_url(int(logo), 400) if str(logo).isdigit() else "",
    }


def liked_songs(con, visitor_id):
    return con.execute(Q.SONG_SELECT + " JOIN song_likes k ON k.song_id = g.id AND k.visitor_id = ? "
                       "ORDER BY k.position, k.created_at", (visitor_id,)).fetchall()


def my_submissions(con, visitor_id):
    contribs = con.execute("SELECT c.*, p.event_date, p.event_name FROM contributions c "
                           "JOIN performances p ON p.id = c.performance_id WHERE c.visitor_id = ? "
                           "ORDER BY c.created_at DESC", (visitor_id,)).fetchall()
    sheets = con.execute("SELECT s.*, g.title AS song_title FROM sheets s JOIN songs g ON g.id = s.song_id "
                         "WHERE s.visitor_id = ? ORDER BY s.created_at DESC", (visitor_id,)).fetchall()
    marquee = con.execute("SELECT * FROM marquee_posts WHERE visitor_id = ? ORDER BY created_at DESC LIMIT 20",
                          (visitor_id,)).fetchall()
    setlists = [dict(c, songs=len(json.loads(c["payload_json"]).get("setlist") or [])) for c in contribs]
    shows = [dict(r, **json.loads(r["payload_json"])) for r in con.execute(
        "SELECT * FROM show_submissions WHERE visitor_id = ? ORDER BY created_at DESC", (visitor_id,))]
    return {"setlists": setlists, "shows": shows, "sheets": sheets, "marquee": marquee}


def contribute_choices(con):
    """「我的投稿」上方的選單：投樂譜選哪首歌、補歌單選哪一場（已經發生的演出）。"""
    past = con.execute("SELECT p.id, p.event_date, p.event_name, p.event_name_en, "
                       "EXISTS (SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id) AS has_setlist "
                       "FROM performances p WHERE p.event_date <= ? ORDER BY p.event_date DESC, p.id DESC",
                       (Q.today(),)).fetchall()
    return {
        "albums": [a for a in Q.albums_with_songs(con) if a["songs"]],
        "missing": [s for s in past if not s["has_setlist"]],     # 還缺歌單的排前面
        "with_setlist": [s for s in past if s["has_setlist"]],
    }


@router.get("/contribute/sheet/")
def contribute_sheet_pick(request: Request, song: int = 0):
    """「我的投稿」選好歌之後按「下一步」：轉到那首歌的投稿頁。"""
    prefix = "/en" if lang_of(request) == "en" else ""
    return RedirectResponse(prefix + ("/contribute/sheet/%d/" % song if song else "/me/?tab=submissions"), status_code=303)


@router.get("/contribute/performance/")
def contribute_performance_pick(request: Request, id: int = 0):
    prefix = "/en" if lang_of(request) == "en" else ""
    return RedirectResponse(prefix + ("/contribute/performance/%d/" % id if id else "/me/?tab=submissions"), status_code=303)


# 台灣的行政區（static/tw-districts.json）：「記在我的帳號」只收這裡面有的「縣市|行政區」
with open(os.path.join(os.path.dirname(__file__), "static", "tw-districts.json"), encoding="utf-8") as _f:
    DISTRICTS = {county + "|" + town[0] for county, _, towns in json.load(_f) for town in towns}


@router.post("/api/me/home")
async def save_home(request: Request, con=Depends(get_con)):
    """住的地方存到帳號（選填）。home 空白＝從帳號刪掉，瀏覽器裡記的不受影響。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    if V.is_guest(visitor):
        return JSONResponse({"error": T(request, "guest_cannot_submit")}, status_code=403)
    home = ((await request.form()).get("home") or "").strip()
    if home and home not in DISTRICTS:
        return JSONResponse({"error": "bad district"}, status_code=400)
    con.execute("UPDATE visitors SET home_district = ? WHERE id = ?", (home, visitor["id"]))
    con.commit()
    return {"ok": True}


ME_TABS = ("footprint", "likes", "recap", "submissions", "settings")


@router.get("/me/")
def me_page(request: Request, con=Depends(get_con)):
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    lang = lang_of(request)
    tabs = [t for t in ME_TABS if not (V.is_guest(visitor) and t == "submissions")]
    tab = request.query_params.get("tab") if request.query_params.get("tab") in tabs else "footprint"
    return render(request, con, "me.html", {
        "tab": tab, "fp": footprint(con, lang, visitor["id"], footprint_filters(request.query_params)),
        "likes": liked_songs(con, visitor["id"]),
        "subs": my_submissions(con, visitor["id"]), "map": taiwan.map_data(), "msg": request.query_params.get("msg"),
        "choices": contribute_choices(con) if tab == "submissions" else None,
        "recap": recap_data(con, lang, visitor) if tab == "recap" else None,
        "tabs": tabs, "guest_until": V.guest_expires(visitor).strftime("%Y/%m/%d %H:%M") if V.is_guest(visitor) else None,
    }, page={"title": "我的", "title_en": "My page"})


@router.post("/me/marquee/{post_id:int}/delete")
def me_delete_marquee(post_id: int, request: Request, con=Depends(get_con)):
    """刪除自己的跑馬燈留言：馬上從首頁消失。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("DELETE FROM marquee_posts WHERE id = ? AND visitor_id = ?", (post_id, visitor["id"]))
    con.commit()
    return RedirectResponse(me_url(request, "marquee_deleted"), status_code=303)


@router.post("/me/sheets/{sheet_id:int}/delete-request")
def me_request_sheet_delete(sheet_id: int, request: Request, con=Depends(get_con)):
    """樂譜要求刪除：記下時間，由管理者確認後刪掉（在那之前照原本的狀態顯示）。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("UPDATE sheets SET delete_requested_at = ? WHERE id = ? AND visitor_id = ? AND delete_requested_at IS NULL",
                (db.now(), sheet_id, visitor["id"]))
    con.commit()
    return RedirectResponse(me_url(request, "sheet_delete_requested"), status_code=303)


def me_url(request, msg_key):
    return ("/en" if lang_of(request) == "en" else "") + "/me/?tab=submissions&msg=" + quote(T(request, msg_key))


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
    if V.is_guest(visitor):                            # 訪客不能開公開個人頁，暱稱不能空白
        if not nickname:
            return RedirectResponse(back + "&msg=" + quote(T(request, "guest_need_nickname")), status_code=303)
        con.execute("UPDATE visitors SET nickname = ?, google_name = ? WHERE id = ?", (nickname, nickname, visitor["id"]))
        con.commit()
        return RedirectResponse(back + "&msg=" + quote(T(request, "saved")), status_code=303)
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
        "fan": row, "fan_name": name, "fp": footprint(con, lang, row["id"], footprint_filters(request.query_params)), "likes": liked_songs(con, row["id"]),
        "map": taiwan.map_data(),
    }, page={"title": name, "title_en": name})


# ==================================================================== 去過、喜歡（按鈕用的 API）
def need_login_json(request):
    return JSONResponse({"error": "login", "login_url": login_url(request, request.headers.get("x-return-to"))},
                        status_code=401)


@router.post("/api/me/attendance")
async def save_attendance(request: Request, con=Depends(get_con)):
    """演出列表按「儲存參與場次」：on 是要標成去過的演出 id、off 是要取消的，都用逗號隔開。
    回傳每一場現在幾位粉絲去過（畫面上的人數跟著更新）。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    form = await request.form()
    def ids(name):
        return {int(x) for x in (form.get(name) or "").split(",") if x.strip().isdigit()}
    on, off = ids("on"), ids("off")
    on -= off
    existing = {r[0] for r in con.execute("SELECT id FROM performances WHERE id IN (%s)" % ",".join("?" * len(on)), list(on))} \
        if on else set()
    con.executemany("INSERT OR IGNORE INTO attendance VALUES (?, ?, ?)", [(visitor["id"], pid, db.now()) for pid in existing])
    con.executemany("DELETE FROM attendance WHERE visitor_id = ? AND performance_id = ?", [(visitor["id"], pid) for pid in off])
    con.commit()
    counts = {pid: con.execute("SELECT COUNT(*) FROM attendance WHERE performance_id = ? AND " + COUNTED, (pid,)).fetchone()[0]
              for pid in existing | off}
    return {"counts": counts}


@router.post("/me/attendance/{performance_id:int}/delete")
async def me_delete_attendance(performance_id: int, request: Request, con=Depends(get_con)):
    """「我的足跡」的去過的場次：刪掉一筆，回到原本的頁面（篩選條件不變）。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("DELETE FROM attendance WHERE visitor_id = ? AND performance_id = ?", (visitor["id"], performance_id))
    con.commit()
    return RedirectResponse(back_to_me((await request.form()).get("back"), request, "attendance_deleted"), status_code=303)


@router.post("/me/likes/{song_id:int}/delete")
async def me_delete_like(song_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("DELETE FROM song_likes WHERE visitor_id = ? AND song_id = ?", (visitor["id"], song_id))
    con.commit()
    return RedirectResponse(back_to_me((await request.form()).get("back"), request, "like_deleted"), status_code=303)


def back_to_me(back, request, msg_key):
    """刪除之後回「我的」的哪裡：只接受 /me/ 或 /en/me/ 開頭的網址，再加上提示訊息。"""
    prefix = "/en" if lang_of(request) == "en" else ""
    back = back if back and re.match(r"^(/en)?/me/(\?|$)", back) else prefix + "/me/"
    back = re.sub(r"([?&])msg=[^&]*&?", r"\1", back).rstrip("?&")
    return back + ("&" if "?" in back else "?") + "msg=" + quote(T(request, msg_key))


@router.post("/api/me/likes/order")
async def order_likes(request: Request, con=Depends(get_con)):
    """「我的 → 喜歡的歌」拖曳排序後存順序。ids 是排好的歌曲 id，用逗號隔開；不是自己喜歡的歌會被略過。"""
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    form = await request.form()
    ids = [int(x) for x in (form.get("ids") or "").split(",") if x.strip().isdigit()]
    con.executemany("UPDATE song_likes SET position = ? WHERE visitor_id = ? AND song_id = ?",
                    [(i, visitor["id"], sid) for i, sid in enumerate(ids)])
    con.commit()
    return {"ok": True}


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
        # 新按的排在最後面，不會打亂自己排好的順序
        last = con.execute("SELECT MAX(position) FROM song_likes WHERE visitor_id = ?", (visitor["id"],)).fetchone()[0]
        con.execute("INSERT INTO song_likes (visitor_id, song_id, created_at, position) VALUES (?, ?, ?, ?)",
                    key + (db.now(), (last or 0) + 1))
        on = True
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM song_likes WHERE song_id = ? AND " + COUNTED, (song_id,)).fetchone()[0]
    return {"on": on, "count": n}


def attended_ids(con, visitor):
    if not visitor:
        return set()
    return {r[0] for r in con.execute("SELECT performance_id FROM attendance WHERE visitor_id = ?", (visitor["id"],))}


def attendance_counts(con):
    return {r[0]: r[1] for r in con.execute("SELECT performance_id, COUNT(*) FROM attendance WHERE " + COUNTED + " GROUP BY performance_id")}


def liked_ids(con, visitor):
    if not visitor:
        return set()
    return {r[0] for r in con.execute("SELECT song_id FROM song_likes WHERE visitor_id = ?", (visitor["id"],))}


def like_counts(con):
    return {r[0]: r[1] for r in con.execute("SELECT song_id, COUNT(*) FROM song_likes WHERE " + COUNTED + " GROUP BY song_id")}


def like_state(con, visitor, song_id):
    n = con.execute("SELECT COUNT(*) FROM song_likes WHERE song_id = ? AND " + COUNTED, (song_id,)).fetchone()[0]
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
    if submit_block(request, visitor):
        error = submit_block(request, visitor)
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


# ==================================================================== 補充現有演出的歌單


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
        "need_login": not visitor or V.is_guest(visitor),
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
    if submit_block(request, visitor):
        return RedirectResponse(back + "?error=" + quote(submit_block(request, visitor)), status_code=303)
    # 現有的演出只收歌單；名稱、地點有錯請寫在「給管理者的話」
    payload = {}
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


# ==================================================================== 新演出
SHOW_TEXT_FIELDS = ("event_name", "venue")


@router.get("/contribute/show/")
def contribute_show_form(request: Request, con=Depends(get_con)):
    return render(request, con, "contribute_show.html", {
        "types": Q.event_types(con), "cities": Q.cities(con), "error": request.query_params.get("error"),
        "need_login": not current_visitor(request, con) or V.is_guest(current_visitor(request, con)),
    }, page={"title": "新增演出資訊", "title_en": "Add a show"})


@router.post("/contribute/show/")
async def contribute_show(request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    form = await request.form()
    back = request.url.path

    def fail(key, **kw):
        return RedirectResponse(back + "?error=" + quote(T(request, key, **kw)), status_code=303)
    if submit_block(request, visitor):
        return RedirectResponse(back + "?error=" + quote(submit_block(request, visitor)), status_code=303)
    date = (form.get("event_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return fail("show_need_date")
    payload = {"event_date": date}
    for f in SHOW_TEXT_FIELDS:
        payload[f] = (form.get(f) or "").strip()[:255]
    if not payload["event_name"]:
        return fail("show_need_name")
    type_id, city_id = form.get("event_type_id"), form.get("city_id")
    if not con.execute("SELECT 1 FROM event_types WHERE id = ?", (type_id,)).fetchone() \
            or not con.execute("SELECT 1 FROM cities WHERE id = ?", (city_id,)).fetchone():
        return fail("show_need_type_city")
    payload["event_type_id"], payload["city_id"] = int(type_id), int(city_id)
    setlist = parse_setlist_text(con, form.get("setlist"))        # 選填：已經演出過的話可以一起附上
    if setlist:
        payload["setlist"] = setlist
    payload["map_url"] = (form.get("map_url") or "").strip()[:500]
    payload["source"] = (form.get("source") or "").strip()[:500]
    if not payload["source"]:
        return fail("contribute_need_source")
    payload["message"] = (form.get("message") or "").strip()[:1000]
    if V.over_daily_limit(con, "show", visitor["id"]):
        return fail("daily_limit", n=V.DAILY_LIMITS["show"])
    con.execute("INSERT INTO show_submissions (visitor_id, payload_json, created_at) VALUES (?, ?, ?)",
                (visitor["id"], json.dumps(payload, ensure_ascii=False), db.now()))
    con.commit()
    me = ("/en" if lang_of(request) == "en" else "") + "/me/?tab=submissions&msg=" + quote(T(request, "show_thanks"))
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
    # COUNTED 裡有 LIKE 'guest:%'，要等 IN (…) 填好之後才接上，不然 % 會被當成格式符號
    likes = dict(con.execute("SELECT sheet_id, COUNT(*) FROM sheet_likes WHERE sheet_id IN (%s) AND " % ",".join("?" * len(rows))
                             + COUNTED + " GROUP BY sheet_id", [r["id"] for r in rows]).fetchall()) if rows else {}
    anon = i18n.t(lang, "anonymous")
    out = []
    for r in rows:
        name = V.display_name(r, r["name_mode"], anon) if r["google_name"] is not None else anon
        out.append(dict(r, author=name, files=files.get(r["id"], []), likes=likes.get(r["id"], 0)))
    return out


@router.get("/sheets/{sheet_id:int}/")
def sheet_page(sheet_id: int, request: Request, con=Depends(get_con)):
    """一份樂譜的頁面：圖、文字譜、演奏影片、讚。只有公開中的看得到。"""
    lang = lang_of(request)
    found = sheets_for_songs(con, lang, [r[0] for r in con.execute("SELECT song_id FROM sheets WHERE id = ?", (sheet_id,))])
    sheet = next((s for s in found if s["id"] == sheet_id), None) or _404()
    song = con.execute(Q.SONG_SELECT + " WHERE g.id = ?", (sheet["song_id"],)).fetchone()
    visitor = current_visitor(request, con)
    liked = bool(visitor and con.execute("SELECT 1 FROM sheet_likes WHERE visitor_id = ? AND sheet_id = ?",
                                         (visitor["id"], sheet_id)).fetchone())
    return render(request, con, "sheet.html", {
        "sheet": sheet, "song": song, "liked": liked, "contact_email": db.get_setting(con, "contact_email"),
    }, page={"title": "%s · %s" % (sheet["title"], song["title"]),
             "title_en": "%s · %s" % (sheet["title"], song["title_en"] or song["title"]),
             "summary": i18n.t("zh", "sheet_by", name=sheet["author"])})


@router.get("/sheets/thumb/{file_id:int}.jpg")
def sheet_thumb(file_id: int, con=Depends(get_con)):
    """樂譜卡片的縮圖：第一張圖縮成寬 240px，存在 MEDIA_ROOT/cache/。只給公開中的樂譜。"""
    row = con.execute("SELECT f.file FROM sheet_files f JOIN sheets s ON s.id = f.sheet_id "
                      "WHERE f.id = ? AND s.status = 'approved'", (file_id,)).fetchone() or _404()
    src, thumb = os.path.join(db.MEDIA_ROOT, row["file"]), V.sheet_thumb_path(row["file"])
    if not os.path.isfile(src):
        _404()
    if not os.path.isfile(thumb):
        from PIL import Image
        os.makedirs(os.path.dirname(thumb), exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail((240, 320), Image.LANCZOS)
            im.convert("RGB").save(thumb + ".tmp", format="JPEG", quality=82)
        os.replace(thumb + ".tmp", thumb)
    return FileResponse(thumb, headers={"Cache-Control": "public, max-age=2592000"})


@router.post("/api/me/sheet-likes/{sheet_id:int}")
def toggle_sheet_like(sheet_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return need_login_json(request)
    if not con.execute("SELECT 1 FROM sheets WHERE id = ? AND status = 'approved'", (sheet_id,)).fetchone():
        raise HTTPException(404)
    key = (visitor["id"], sheet_id)
    if con.execute("SELECT 1 FROM sheet_likes WHERE visitor_id = ? AND sheet_id = ?", key).fetchone():
        con.execute("DELETE FROM sheet_likes WHERE visitor_id = ? AND sheet_id = ?", key)
        on = False
    else:
        con.execute("INSERT INTO sheet_likes (visitor_id, sheet_id, created_at) VALUES (?, ?, ?)", key + (db.now(),))
        on = True
    con.commit()
    return {"on": on, "count": con.execute("SELECT COUNT(*) FROM sheet_likes WHERE sheet_id = ? AND " + COUNTED,
                                           (sheet_id,)).fetchone()[0]}


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
        "song": song, "error": request.query_params.get("error"), "need_login": not current_visitor(request, con) or V.is_guest(current_visitor(request, con)),
        "max_files": SHEET_MAX_FILES, "contact_email": db.get_setting(con, "contact_email"),
    }, page={"title": "投稿樂譜", "title_en": "Submit sheet music"})


@router.post("/contribute/sheet/{song_id:int}/")
async def contribute_sheet(song_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    con.execute("SELECT 1 FROM songs WHERE id = ?", (song_id,)).fetchone() or _404()
    return await save_sheet(request, con, visitor, song_id, None)


def arrange_sheet_files(order, kept, stored):
    """照網頁上排好的順序組出 (檔名, 寬, 高) 的清單；order 沒列到的（不該發生）接在最後。"""
    by_id = {f["id"]: (f["file"], f["width"], f["height"]) for f in kept}
    out, used_k, used_n = [], set(), set()
    for kind, i in order:
        if not i.isdigit():
            continue
        i = int(i)
        if kind == "k" and i in by_id and i not in used_k:
            out.append(by_id[i]); used_k.add(i)
        elif kind == "n" and i < len(stored) and i not in used_n:
            out.append(stored[i]); used_n.add(i)
    out += [v for i, v in by_id.items() if i not in used_k]
    out += [v for i, v in enumerate(stored) if i not in used_n]
    return out


def editable_sheet(con, visitor, sheet_id):
    """投稿者可以編輯的那一筆 → (原本那筆, 要改的那筆)。公開中的樂譜改的是待審的修改版（還沒有就是 None，存檔時新增）。
    下架、要求刪除中的不能改。"""
    sheet = con.execute("SELECT * FROM sheets WHERE id = ? AND visitor_id = ?", (sheet_id, visitor["id"])).fetchone()
    if not sheet or sheet["status"] == "removed" or sheet["delete_requested_at"]:
        return None, None
    if sheet["status"] == "approved":
        rev = con.execute("SELECT * FROM sheets WHERE replaces_id = ? AND status = 'pending'", (sheet_id,)).fetchone()
        return sheet, rev
    return sheet, sheet


@router.get("/contribute/sheet/edit/{sheet_id:int}/")
def edit_sheet_form(sheet_id: int, request: Request, con=Depends(get_con)):
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    original, current = editable_sheet(con, visitor, sheet_id)
    if not original:
        _404()
    shown = current or original                        # 表單裡預先填好的內容
    return render(request, con, "contribute_sheet.html", {
        "song": con.execute(Q.SONG_SELECT + " WHERE g.id = ?", (original["song_id"],)).fetchone(),
        "sheet": shown, "live": original["status"] == "approved",
        "files": con.execute("SELECT * FROM sheet_files WHERE sheet_id = ? ORDER BY position", (shown["id"],)).fetchall(),
        "error": request.query_params.get("error"), "need_login": False,
        "max_files": SHEET_MAX_FILES, "contact_email": db.get_setting(con, "contact_email"),
    }, page={"title": "編輯樂譜", "title_en": "Edit sheet music"})


@router.post("/contribute/sheet/edit/{sheet_id:int}/")
async def edit_sheet(sheet_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    original, current = editable_sheet(con, visitor, sheet_id)
    if not original:
        _404()
    return await save_sheet(request, con, visitor, original["song_id"], original, current)


async def save_sheet(request, con, visitor, song_id, original, current=None):
    """新投稿（original 是 None）或編輯。編輯一律重新審核：
    還沒公開的直接改那一筆、狀態回到待審；公開中的另存一筆修改版（replaces_id），通過前照樣顯示原本的。"""
    form = await request.form()
    back = request.url.path

    def fail(key, **kw):
        return RedirectResponse(back + "?error=" + quote(T(request, key, **kw)), status_code=303)
    if submit_block(request, visitor):
        return RedirectResponse(back + "?error=" + quote(submit_block(request, visitor)), status_code=303)
    title = (form.get("title") or "").strip()[:80]
    text_body = (form.get("text_body") or "").strip()[:20000]
    video = (form.get("video_url") or "").strip()[:500]
    uploads = [u for u in form.getlist("files") if getattr(u, "filename", "")]
    # 編輯時勾選留下的舊圖檔（公開中第一次修改，舊圖檔來自原本那份）
    source = current or original
    old_files = con.execute("SELECT * FROM sheet_files WHERE sheet_id = ? ORDER BY position",
                            (source["id"],)).fetchall() if source else []
    # 圖片順序：網頁上排好的順序放在 order，例如 "k:12,n:0,k:9"（k＝留下的舊圖 id、n＝這次上傳的第幾張）。
    # 沒有 order（瀏覽器沒跑 JavaScript）就用勾選的舊圖（keep）＋新圖，照原本順序。
    order = [tuple(tok.split(":", 1)) for tok in (form.get("order") or "").split(",") if ":" in tok]
    if form.get("order") is not None:
        keep_ids = {int(i) for kind, i in order if kind == "k" and i.isdigit()}
    else:
        keep_ids = {int(x) for x in form.getlist("keep") if str(x).isdigit()}
    kept = [f for f in old_files if f["id"] in keep_ids]
    if not form.get("own_work"):
        return fail("sheet_need_own")
    if not title:
        return fail("sheet_need_title")
    if not uploads and not kept and not text_body:
        return fail("sheet_need_content")
    if len(uploads) + len(kept) > SHEET_MAX_FILES:
        return fail("sheet_too_many", n=SHEET_MAX_FILES)
    if video and urlparse(video).scheme not in ("http", "https"):
        return fail("sheet_bad_video")
    new_row = not current                              # 新投稿，或公開中的樂譜第一次修改
    if new_row and V.over_daily_limit(con, "sheet", visitor["id"]):
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
    files = arrange_sheet_files(order, kept, stored)
    dropped = []
    if new_row:
        sheet_id = con.execute("INSERT INTO sheets (visitor_id, song_id, title, text_body, video_url, name_mode, created_at, "
                               "replaces_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (visitor["id"], song_id, title, text_body, video, mode, db.now(),
                                original["id"] if original else None)).lastrowid
    else:
        sheet_id = current["id"]
        con.execute("UPDATE sheets SET title = ?, text_body = ?, video_url = ?, name_mode = ?, status = 'pending', "
                    "admin_note = '', reviewed_at = NULL WHERE id = ?", (title, text_body, video, mode, sheet_id))
        dropped = [f["file"] for f in old_files if f["id"] not in keep_ids]
        con.execute("DELETE FROM sheet_files WHERE sheet_id = ?", (sheet_id,))
    con.executemany("INSERT INTO sheet_files (sheet_id, position, file, width, height) VALUES (?, ?, ?, ?, ?)",
                    [(sheet_id, i, name, w, h) for i, (name, w, h) in enumerate(files)])
    con.commit()
    V.remove_unused_media(con, dropped)                 # 修改版還在用原本那份的圖檔時不會刪
    return RedirectResponse(me_url(request, "sheet_edit_thanks" if original else "sheet_thanks"), status_code=303)
