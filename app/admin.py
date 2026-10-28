"""後台（/admin）。

所有頁面都要登入；會寫入的請求一律 POST，並檢查 Origin 是不是本站（cookie 也設了 SameSite=Lax），
擋掉從別的網站偷送的表單。寫入後一律轉址回列表或編輯頁（POST/Redirect/GET），訊息放在 ?msg=。

結構：
- 簡單的資料表（演出類型、城市、專輯、歌曲）共用一組列表／表單，欄位定義在 MODELS。
- 演出（含歌單編輯）、歌詞（含段落編輯）、頁面（含富文字編輯）、圖片、設定各自有頁面。
"""
import datetime
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, navigation, queries as Q, taiwan

HERE = os.path.dirname(os.path.abspath(__file__))
router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.globals.update(image_url=Q.image_url, page_url=Q.page_url)
templates.env.filters["fromjson"] = json.loads


def site_logo_id():
    """後台頁首與分頁圖示用的 Logo（跟前台同一個設定）；沒設定回傳 None。"""
    con = db.connect()
    try:
        value = db.get_setting(con, "site_logo_id")
    finally:
        con.close()
    return int(value) if str(value).isdigit() else None


templates.env.globals["site_logo_id"] = site_logo_id

PER_PAGE = 50
LINE_BREAK = "⏎"      # 歌詞編輯器裡代表「同一格內換行」的符號


class LoginRequired(Exception):
    pass


def login_redirect(request, exc):
    return RedirectResponse("/admin/login?next=" + quote(request.url.path), status_code=303)


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def same_origin(request):
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True
    host = urlparse(origin).netloc
    return host in (request.headers.get("host"), request.headers.get("x-forwarded-host"))


def user_required(request: Request, con=Depends(get_con)):
    user = auth.current_user(con, request.cookies.get(auth.COOKIE))
    if not user:
        raise LoginRequired()
    if request.method == "POST" and not same_origin(request):
        raise HTTPException(403, "表單來源不是本站")
    request.state.user = user
    return con


def done(url, msg="已儲存"):
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url + sep + "msg=" + quote(msg), status_code=303)


def page(request, name, ctx=None, status=200):
    context = {"request": request, "user": getattr(request.state, "user", None),
               "msg": request.query_params.get("msg"), "nav": ctx.pop("nav", "") if ctx else ""}
    context.update(ctx or {})
    return templates.TemplateResponse(request, "admin/" + name, context, status_code=status)


def as_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def check_slug(slug, allow_slash=True, allow_empty=False):
    slug = (slug or "").strip().strip("/").lower()
    pattern = r"[a-z0-9][a-z0-9_\-]*(/[a-z0-9][a-z0-9_\-]*)*" if allow_slash else r"[a-z0-9][a-z0-9_\-]*"
    if not slug and allow_empty:
        return ""
    if not re.fullmatch(pattern, slug):
        raise ValueError("網址只能用英文小寫、數字、- 和 _%s。" % ("，層級用 / 分隔" if allow_slash else ""))
    return slug


def rich_value(form, name, old):
    """富文字欄位：只有編輯器正常載入（表單帶著 rich_ok）才用送來的值，否則保留原本的內容。"""
    return form.get(name) or "" if form.get("rich_ok") else (old or "")


def slugify(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ==================================================================== 登入
@router.get("/login")
def login_form(request: Request):
    return page(request, "login.html", {"next": request.query_params.get("next", "/admin/")})


@router.post("/login")
async def login_submit(request: Request, con=Depends(get_con)):
    if not same_origin(request):
        raise HTTPException(403)
    form = await request.form()
    nxt = form.get("next") or "/admin/"
    if not nxt.startswith("/admin"):
        nxt = "/admin/"
    try:
        token = auth.login(con, form.get("username"), form.get("password"))
    except auth.AuthError as e:
        return page(request, "login.html", {"error": str(e), "next": nxt, "username": form.get("username")}, 400)
    resp = RedirectResponse(nxt, status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", secure=https,
                    max_age=auth.MAX_DAYS * 86400, path="/")
    return resp


@router.post("/logout")
def logout(request: Request, con=Depends(user_required)):
    auth.logout(con, request.cookies.get(auth.COOKIE))
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@router.get("/account")
def account(request: Request, con=Depends(user_required)):
    users = con.execute("SELECT id, username, is_active, last_login FROM users ORDER BY id").fetchall()
    return page(request, "account.html", {"nav": "account", "users": users})


@router.post("/account")
async def account_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    user = request.state.user
    try:
        if form.get("action") == "password":
            if not auth.verify_password(form.get("current") or "", user["password"]):
                raise auth.AuthError("目前的密碼不對。")
            if form.get("new") != form.get("confirm"):
                raise auth.AuthError("兩次輸入的新密碼不一樣。")
            auth.set_password(con, user["id"], form.get("new"))
            return done("/admin/login", "密碼已更新，請重新登入")
        if form.get("action") == "create":
            name = (form.get("username") or "").strip()
            if not name:
                raise auth.AuthError("請填帳號。")
            if len(form.get("password") or "") < 8:
                raise auth.AuthError("密碼至少 8 個字元。")
            con.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                        (name, auth.hash_password(form.get("password")), db.now()))
            con.commit()
            return done("/admin/account", "已新增帳號 %s" % name)
    except (auth.AuthError, sqlite3.IntegrityError) as e:
        msg = str(e) if isinstance(e, auth.AuthError) else "這個帳號已經有了。"
        return done("/admin/account", msg)
    return done("/admin/account", "沒有變更")


# ==================================================================== 總覽
@router.get("/")
def dashboard(request: Request, con=Depends(user_required)):
    today = Q.today()
    return page(request, "dashboard.html", {
        "nav": "dashboard",
        "review": con.execute("SELECT id, title, review_json FROM lyrics WHERE review_json != '[]' "
                              "ORDER BY sort_order").fetchall(),
        "unmapped": con.execute("SELECT COUNT(*) FROM songs WHERE lyrics_id IS NULL").fetchone()[0],
        "missing_setlists": con.execute(
            "SELECT COUNT(*) FROM performances p WHERE p.event_date <= ? AND NOT EXISTS "
            "(SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id)", (today,)).fetchone()[0],
        "upcoming": Q.upcoming(con, 5),
        "counts": {label: con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                   for table, label in [("performances", "演出"), ("songs", "歌曲"), ("lyrics", "歌詞"),
                                        ("pages", "頁面"), ("images", "圖片")]},
    })


# ==================================================================== 簡單資料表
def F(name, label, kind="text", required=False, help="", choices=None):
    return {"name": name, "label": label, "kind": kind, "required": required, "help": help, "choices": choices}


def city_choices(con):
    names = {**{k: v[0] for k, v in taiwan.CITIES.items()}, **{k: v[0] for k, v in taiwan.INSETS.items()}}
    return [("", "（不畫在地圖上）")] + [(k, "%s（%s）" % (v, k)) for k, v in names.items()]


MODELS = {
    "event-types": {
        "table": "event_types", "title": "演出類型", "order": "sort_order, name", "search": ["name", "name_en"],
        "columns": [("name", "名稱"), ("name_en", "英文"), ("sort_order", "排序")],
        "fields": [F("name", "名稱", required=True), F("name_en", "英文名稱"),
                   F("sort_order", "排序", "int", help="數字越小越前面；圖表的顏色也照這個順序")],
    },
    "cities": {
        "table": "cities", "title": "城市", "order": "sort_order, name", "search": ["name", "name_en"],
        "columns": [("name", "名稱"), ("name_en", "英文"), ("map_key", "地圖位置"), ("sort_order", "排序")],
        "fields": [F("name", "名稱", required=True), F("name_en", "英文名稱"),
                   F("map_key", "地圖上的縣市", "select", choices=city_choices,
                     help="演出頁的地圖把這個城市畫在哪裡；海外選「不畫在地圖上」"),
                   F("sort_order", "排序", "int")],
    },
    "albums": {
        "table": "albums", "title": "專輯", "order": "sort_order, id", "search": ["name", "name_en"],
        "columns": [("cover_image_id", ""), ("name", "名稱"), ("name_en", "英文"), ("sort_order", "排序")],
        "fields": [F("name", "名稱", required=True), F("name_en", "英文名稱"),
                   F("cover_image_id", "封面", "image", help="建議正方形"),
                   F("release_date", "發行日期", "text", help="例：2025-04-18，可以只填年份"),
                   F("description", "介紹", "textarea"), F("description_en", "英文介紹", "textarea"),
                   F("sort_order", "排序", "int", help="歌詞頁的專輯方塊照這個順序排")],
    },
    "songs": {
        "table": "songs", "title": "歌曲", "order": "sort_order, id", "search": ["title", "title_en", "artist"],
        "filter": ("album_id", "SELECT id, name FROM albums ORDER BY sort_order, id"),
        "columns": [("title", "曲名"), ("title_en", "英文"), ("album_id", "專輯"), ("lyrics_id", "歌詞"),
                    ("listen_url", "試聽"), ("sort_order", "排序")],
        "fields": [F("title", "曲名", required=True), F("title_en", "英文曲名"),
                   F("artist", "原唱", help="翻唱才填；163braces 自己的歌留空"), F("artist_en", "原唱（英文）"),
                   F("album_id", "專輯", "fk", required=True, choices="SELECT id, name FROM albums ORDER BY sort_order, id"),
                   F("lyrics_id", "歌詞", "fk", choices="SELECT id, title FROM lyrics ORDER BY sort_order, id",
                     help="改編版、日文版可以跟原曲選同一份歌詞"),
                   F("cover_image_id", "單曲封面", "image", help="空白就用專輯封面"),
                   F("listen_url", "試聽影片", "url", help="YouTube 網址；首頁「隨機聆聽」只會挑有填這欄、也有歌詞的歌"),
                   F("sort_order", "排序", "int")],
    },
}


def resolve_choices(con, field):
    ch = field["choices"]
    if callable(ch):
        return ch(con)
    if isinstance(ch, str):
        return [(r[0], r[1]) for r in con.execute(ch)]
    return ch or []


@router.get("/m/{model}/")
def model_list(model: str, request: Request, con=Depends(user_required)):
    spec = MODELS.get(model) or _404()
    q = (request.query_params.get("q") or "").strip()
    where, args = [], []
    if q:
        where.append("(" + " OR ".join("%s LIKE ?" % c for c in spec["search"]) + ")")
        args += ["%" + q + "%"] * len(spec["search"])
    flt, flt_value = spec.get("filter"), as_int(request.query_params.get("f"))
    if flt and flt_value:
        where.append("%s = ?" % flt[0]); args.append(flt_value)
    rows = con.execute("SELECT * FROM %s%s ORDER BY %s" % (
        spec["table"], " WHERE " + " AND ".join(where) if where else "", spec["order"]), args).fetchall()
    lookups = {f["name"]: dict(resolve_choices(con, f)) for f in spec["fields"] if f["kind"] in ("fk", "select")}
    return page(request, "model_list.html", {
        "nav": model, "model": model, "spec": spec, "rows": rows, "q": q, "lookups": lookups,
        "filter_choices": [(r[0], r[1]) for r in con.execute(flt[1])] if flt else None, "filter_value": flt_value,
    })


@router.get("/m/{model}/{item_id}")
def model_form(model: str, item_id: str, request: Request, con=Depends(user_required)):
    spec = MODELS.get(model) or _404()
    row = None
    if item_id != "new":
        row = con.execute("SELECT * FROM %s WHERE id = ?" % spec["table"], (as_int(item_id),)).fetchone() or _404()
    choices = {f["name"]: resolve_choices(con, f) for f in spec["fields"] if f["kind"] in ("fk", "select")}
    return page(request, "model_form.html", {"nav": model, "model": model, "spec": spec, "row": row,
                                             "choices": choices})


@router.post("/m/{model}/{item_id}")
async def model_save(model: str, item_id: str, request: Request, con=Depends(user_required)):
    spec = MODELS.get(model) or _404()
    form = await request.form()
    if form.get("action") == "delete":
        try:
            con.execute("DELETE FROM %s WHERE id = ?" % spec["table"], (as_int(item_id),))
            con.commit()
        except sqlite3.IntegrityError:
            return done("/admin/m/%s/%s" % (model, item_id), "還有資料在使用這一筆（例如演出或歌曲），不能刪除")
        return done("/admin/m/%s/" % model, "已刪除")
    values = {}
    for f in spec["fields"]:
        v = (form.get(f["name"]) or "").strip()
        if f["kind"] in ("int",):
            v = as_int(v, 0)
        elif f["kind"] in ("fk", "image"):
            v = as_int(v)
        if f["required"] and v in ("", None):
            return done("/admin/m/%s/%s" % (model, item_id), "「%s」必填" % f["label"])
        values[f["name"]] = v
    cols = list(values)
    if item_id == "new":
        cur = con.execute("INSERT INTO %s (%s) VALUES (%s)" % (spec["table"], ", ".join(cols), ", ".join("?" * len(cols))),
                          [values[c] for c in cols])
        item_id = cur.lastrowid
    else:
        con.execute("UPDATE %s SET %s WHERE id = ?" % (spec["table"], ", ".join("%s = ?" % c for c in cols)),
                    [values[c] for c in cols] + [as_int(item_id)])
    con.commit()
    if form.get("action") == "save_new":
        return done("/admin/m/%s/new" % model)
    return done("/admin/m/%s/%s" % (model, item_id))


def _404():
    raise HTTPException(404)


# ==================================================================== 歌曲 ↔ 歌詞
@router.get("/mapping")
def mapping(request: Request, con=Depends(user_required)):
    songs = con.execute("SELECT g.*, a.name AS album_name FROM songs g JOIN albums a ON a.id = g.album_id "
                        "ORDER BY g.lyrics_id IS NOT NULL, a.sort_order, g.sort_order").fetchall()
    lyrics = con.execute("SELECT id, title, title_en FROM lyrics ORDER BY sort_order, id").fetchall()
    return page(request, "mapping.html", {"nav": "mapping", "songs": songs, "lyrics": lyrics})


@router.post("/mapping")
async def mapping_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    for key, value in form.items():
        if key.startswith("song_"):
            con.execute("UPDATE songs SET lyrics_id = ? WHERE id = ?", (as_int(value), as_int(key[5:])))
    con.commit()
    return done("/admin/mapping")


# ==================================================================== 演出
@router.get("/performances/")
def performance_list(request: Request, con=Depends(user_required)):
    p = request.query_params
    where, args = [], []
    if p.get("q"):
        where.append("(p.event_name LIKE ? OR p.event_name_en LIKE ? OR p.venue LIKE ?)")
        args += ["%" + p["q"] + "%"] * 3
    if p.get("year"):
        where.append("substr(p.event_date, 1, 4) = ?"); args.append(p["year"])
    if as_int(p.get("type")):
        where.append("p.event_type_id = ?"); args.append(as_int(p["type"]))
    if p.get("missing"):
        where.append("p.event_date <= ? AND NOT EXISTS (SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id)")
        args.append(Q.today())
    sql_where = " WHERE " + " AND ".join(where) if where else ""
    total = con.execute("SELECT COUNT(*) FROM performances p" + sql_where, args).fetchone()[0]
    page_no = max(1, as_int(p.get("page"), 1))
    rows = con.execute(Q.PERF_SELECT + sql_where + " ORDER BY p.event_date DESC, p.id DESC LIMIT ? OFFSET ?",
                       args + [PER_PAGE, (page_no - 1) * PER_PAGE]).fetchall()
    query = {k: v for k, v in p.items() if k not in ("page", "msg")}
    return page(request, "performances.html", {
        "nav": "performances", "rows": rows, "total": total, "page_no": page_no,
        "pages": (total + PER_PAGE - 1) // PER_PAGE, "query": query, "years": Q.available_years(con),
        "types": Q.event_types(con), "today": Q.today(),
    })


def song_options(con):
    return con.execute("SELECT g.id, g.title, g.title_en, g.artist, a.name AS album_name FROM songs g "
                       "JOIN albums a ON a.id = g.album_id ORDER BY a.sort_order, g.sort_order, g.id").fetchall()


@router.get("/performances/{item_id}")
def performance_form(item_id: str, request: Request, con=Depends(user_required)):
    row, items = None, []
    if item_id != "new":
        row = con.execute("SELECT * FROM performances WHERE id = ?", (as_int(item_id),)).fetchone() or _404()
        items = con.execute("SELECT * FROM setlist_items WHERE performance_id = ? ORDER BY position, id",
                            (row["id"],)).fetchall()
    copy = as_int(request.query_params.get("copy"))
    if copy and not row:      # 「複製這場」：帶入原本的資料，日期留空
        src = con.execute("SELECT * FROM performances WHERE id = ?", (copy,)).fetchone()
        row = dict(src, id=None, event_date="") if src else None
    return page(request, "performance_form.html", {
        "nav": "performances", "row": row, "items": items, "songs": song_options(con),
        "types": Q.event_types(con), "cities": Q.cities(con),
    })


@router.post("/performances/{item_id}")
async def performance_save(item_id: str, request: Request, con=Depends(user_required)):
    form = await request.form()
    if form.get("action") == "delete":
        con.execute("DELETE FROM performances WHERE id = ?", (as_int(item_id),))
        con.commit()
        return done("/admin/performances/", "已刪除")
    data = {k: (form.get(k) or "").strip() for k in
            ("event_date", "event_name", "event_name_en", "venue", "venue_en")}
    data["event_type_id"] = as_int(form.get("event_type_id"))
    data["city_id"] = as_int(form.get("city_id"))
    data["setlist_order_uncertain"] = 1 if form.get("setlist_order_uncertain") else 0
    missing = [label for key, label in [("event_date", "日期"), ("event_name", "名稱"), ("event_type_id", "類型"),
                                        ("city_id", "城市")] if not data[key]]
    if missing:
        return done(request.url.path, "「%s」必填" % "、".join(missing))
    try:
        datetime.date.fromisoformat(data["event_date"])
    except ValueError:
        return done(request.url.path, "日期格式不對")

    # 歌單：每一列是 song（曲庫 id，空白＝自訂）＋ custom ＋ note，順序就是畫面上的順序
    setlist = []
    for song, custom, note in zip(form.getlist("item_song"), form.getlist("item_custom"), form.getlist("item_note")):
        song, custom, note = as_int(song), (custom or "").strip(), (note or "").strip()
        if song:
            custom = ""
        if song or custom:
            setlist.append((song, custom, note))

    cols = list(data)
    if item_id == "new":
        item_id = con.execute("INSERT INTO performances (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                              [data[c] for c in cols]).lastrowid
    else:
        item_id = as_int(item_id)
        con.execute("UPDATE performances SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                    [data[c] for c in cols] + [item_id])
    con.execute("DELETE FROM setlist_items WHERE performance_id = ?", (item_id,))
    con.executemany("INSERT INTO setlist_items (performance_id, position, song_id, custom_title, note) "
                    "VALUES (?, ?, ?, ?, ?)", [(item_id, i, s, c, n) for i, (s, c, n) in enumerate(setlist)])
    con.commit()
    if form.get("action") == "save_new":
        return done("/admin/performances/new")
    return done("/admin/performances/%d" % item_id)


# ==================================================================== 歌詞
@router.get("/lyrics/")
def lyrics_list(request: Request, con=Depends(user_required)):
    rows = con.execute("""
        SELECT l.*, (SELECT group_concat(title, '、') FROM songs WHERE lyrics_id = l.id) AS song_titles
        FROM lyrics l ORDER BY l.review_json = '[]', l.sort_order, l.id""").fetchall()
    return page(request, "lyrics_list.html", {"nav": "lyrics", "rows": rows,
                                              "prefix": Q.lyrics_prefix(con)})


@router.get("/lyrics/{item_id}")
def lyrics_form(item_id: str, request: Request, con=Depends(user_required)):
    row, linked = None, []
    if item_id != "new":
        row = con.execute("SELECT * FROM lyrics WHERE id = ?", (as_int(item_id),)).fetchone() or _404()
        linked = [r[0] for r in con.execute("SELECT id FROM songs WHERE lyrics_id = ?", (row["id"],))]
    blocks = json.loads(row["sections_json"]) if row else [{"type": "section", "name": "", "name_alt": "", "lines": []}]
    # 編輯器用「左欄一行一句、右欄一行一句」兩個文字框；同一格裡的換行用 ⏎ 表示
    for b in blocks:
        if b.get("type") == "section":
            b["left_text"] = "\n".join(ln["left"].replace("\r\n", "\n").replace("\n", LINE_BREAK) for ln in b["lines"])
            b["right_text"] = "\n".join(ln["right"].replace("\r\n", "\n").replace("\n", LINE_BREAK) for ln in b["lines"])
    return page(request, "lyrics_form.html", {
        "nav": "lyrics", "row": row, "blocks": blocks, "videos": json.loads(row["videos_json"]) if row else [],
        "review": json.loads(row["review_json"]) if row else [], "songs": song_options(con), "linked": linked,
        "prefix": Q.lyrics_prefix(con), "line_break": LINE_BREAK,
    })


@router.post("/lyrics/{item_id}")
async def lyrics_save(item_id: str, request: Request, con=Depends(user_required)):
    form = await request.form()
    if form.get("action") == "delete":
        con.execute("DELETE FROM lyrics WHERE id = ?", (as_int(item_id),))
        con.commit()
        return done("/admin/lyrics/", "已刪除")
    back = request.url.path
    try:
        slug = check_slug(form.get("slug") or slugify(form.get("title_en") or ""), allow_slash=False)
    except ValueError as e:
        return done(back, str(e))
    # 歌詞與影片由頁面上的編輯器在送出時填進來；欄位是空字串代表編輯器沒有正常載入（JS 出錯、
    # 網路斷了沒載到 Quill），這時絕對不能當成「全部刪光」存進去
    if not form.get("blocks_json") or not form.get("videos_json"):
        return done(back, "歌詞編輯器沒有正常載入，這次沒有存檔。請重新整理頁面再試。")
    try:
        blocks = json.loads(form["blocks_json"])
        videos = [v for v in json.loads(form["videos_json"]) if v.get("url")]
    except ValueError:
        return done(back, "段落資料讀不懂，請重新整理後再試")
    for b in blocks:
        if b.get("type") == "section":
            b["lines"] = [{"left": ln.get("left", "").replace(LINE_BREAK, "\n"),
                           "right": ln.get("right", "").replace(LINE_BREAK, "\n")} for ln in b.get("lines", [])]
    old_row = con.execute("SELECT * FROM lyrics WHERE id = ?", (as_int(item_id),)).fetchone() if item_id != "new" else None
    mode = form.get("display_mode") if form.get("display_mode") in ("bilingual", "duet", "single") else "bilingual"
    data = {
        "slug": slug, "title": (form.get("title") or "").strip(), "title_en": (form.get("title_en") or "").strip(),
        "artist": form.get("artist") or "", "composer": form.get("composer") or "",
        "lyricist": form.get("lyricist") or "", "release_year": as_int(form.get("release_year")),
        "display_mode": mode, "left_label": form.get("left_label") or "", "right_label": form.get("right_label") or "",
        "intro_html": rich_value(form, "intro_html", old_row["intro_html"] if old_row else ""),
        "intro_html_en": rich_value(form, "intro_html_en", old_row["intro_html_en"] if old_row else ""),
        "sections_json": json.dumps(blocks, ensure_ascii=False), "videos_json": json.dumps(videos, ensure_ascii=False),
        "published": 1 if form.get("published") else 0, "sort_order": as_int(form.get("sort_order"), 0),
        "updated_at": db.now(),
    }
    if not data["title"]:
        return done(back, "請填曲名")
    if form.get("review_done"):
        data["review_json"] = "[]"
    cols = list(data)
    try:
        if item_id == "new":
            item_id = con.execute("INSERT INTO lyrics (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                                  [data[c] for c in cols]).lastrowid
        else:
            item_id = as_int(item_id)
            old = con.execute("SELECT slug FROM lyrics WHERE id = ?", (item_id,)).fetchone()
            con.execute("UPDATE lyrics SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                        [data[c] for c in cols] + [item_id])
            if old and old["slug"] != slug:
                prefix = Q.lyrics_prefix(con)
                add_redirects(con, prefix + old["slug"] + "/", prefix + slug + "/")
    except sqlite3.IntegrityError:
        return done(back, "網址「%s」已經有別的歌詞在用" % slug)
    # 使用這份歌詞的歌曲
    chosen = {as_int(v) for v in form.getlist("song_ids")}
    con.execute("UPDATE songs SET lyrics_id = NULL WHERE lyrics_id = ? AND id NOT IN (%s)"
                % ",".join("?" * len(chosen) or "0"), [item_id] + list(chosen))
    for sid in chosen:
        con.execute("UPDATE songs SET lyrics_id = ? WHERE id = ?", (item_id, sid))
    con.commit()
    return done("/admin/lyrics/%d" % item_id)


def add_redirects(con, old, new):
    """舊網址轉到新網址（中英文各一筆），並把原本指向舊網址的轉址也改指新網址。"""
    for prefix in ("", "/en"):
        con.execute("INSERT OR REPLACE INTO redirects VALUES (?, ?)", (prefix + old, prefix + new))
        con.execute("UPDATE redirects SET new_path = ? || substr(new_path, ?) WHERE new_path = ? OR new_path LIKE ?",
                    (prefix + new, len(prefix + old) + 1, prefix + old, prefix + old + "?%"))
        con.execute("DELETE FROM redirects WHERE old_path = ?", (prefix + new,))


# ==================================================================== 歌詞索引的順序
@router.get("/lyrics-order")
def lyrics_order(request: Request, con=Depends(user_required)):
    albums = []
    for a in con.execute("SELECT * FROM albums ORDER BY sort_order, id"):
        songs = con.execute("""
            SELECT g.id, g.title, g.title_en, g.cover_image_id, l.slug AS lyrics_slug, l.published AS lyrics_published
            FROM songs g LEFT JOIN lyrics l ON l.id = g.lyrics_id
            WHERE g.album_id = ? ORDER BY g.sort_order, g.id""", (a["id"],)).fetchall()
        cover = a["cover_image_id"] or next((s["cover_image_id"] for s in songs if s["cover_image_id"]), None)
        albums.append({"id": a["id"], "name": a["name"], "release_date": a["release_date"],
                       "cover": Q.image_url(cover, 240) if cover else "",
                       "songs": [{"id": s["id"], "title": s["title"], "title_en": s["title_en"],
                                  "has_lyrics": bool(s["lyrics_slug"] and s["lyrics_published"])} for s in songs]})
    orphans = [{"id": r["id"], "title": r["title"], "title_en": r["title_en"], "published": r["published"]}
               for r in con.execute("SELECT * FROM lyrics WHERE id NOT IN (SELECT lyrics_id FROM songs "
                                    "WHERE lyrics_id IS NOT NULL) ORDER BY sort_order, id")]
    return page(request, "lyrics_order.html", {
        "nav": "lyrics-order", "prefix": Q.lyrics_prefix(con),
        "data": {"albums": albums, "orphans": orphans,
                 "other_position": Q.other_lyrics_position(con, len(albums))}})


@router.post("/lyrics-order")
async def lyrics_order_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    if not form.get("order_json"):
        return done("/admin/lyrics-order", "排序編輯器沒有正常載入，這次沒有存檔。請重新整理頁面再試。")
    try:
        data = json.loads(form["order_json"])
        album_ids = [int(a["id"]) for a in data["albums"]]
        orphan_ids = [int(i) for i in data["orphans"]]
        other_position = min(max(0, int(data["other_position"])), len(album_ids))
    except (ValueError, KeyError, TypeError):
        return done("/admin/lyrics-order", "資料讀不懂，請重新整理後再試")
    known = {r[0] for r in con.execute("SELECT id FROM albums")}
    if set(album_ids) != known:
        return done("/admin/lyrics-order", "專輯清單跟資料庫對不上（可能有人同時在改），請重新整理後再試")
    # 專輯照拖好的順序編號；歌曲的排序是全站連號（第一張專輯的歌最小），
    # 這樣其他照歌曲排序的地方（例如年度回顧的選歌）也會跟專輯順序一致
    n = 0
    for i, album in enumerate(data["albums"]):
        con.execute("UPDATE albums SET sort_order = ? WHERE id = ?", (i + 1, int(album["id"])))
        for song_id in album["songs"]:
            n += 1
            con.execute("UPDATE songs SET sort_order = ?, album_id = ? WHERE id = ?", (n, int(album["id"]), int(song_id)))
    for i, lyrics_id in enumerate(orphan_ids):
        con.execute("UPDATE lyrics SET sort_order = ? WHERE id = ?", (i + 1, lyrics_id))
    db.set_setting(con, "lyrics_other_position", other_position)     # 「其他歌詞」排在第幾張專輯後面
    con.commit()
    return done("/admin/lyrics-order")


# ==================================================================== 頁面
KIND_LABELS = {"home": "首頁", "performances": "演出（列表、統計、歌單、年度回顧）", "lyrics": "歌詞索引",
               "articles": "文章列表", "article": "文章", "page": "一般頁面"}
FIXED_KINDS = ("home", "performances", "lyrics", "articles")


@router.get("/pages/")
def pages_list(request: Request, con=Depends(user_required)):
    rows = con.execute("SELECT * FROM pages ORDER BY kind NOT IN ('home', 'performances', 'lyrics', "
                       "'articles'), kind = 'article', sort_order, published_at DESC, id").fetchall()
    return page(request, "pages_list.html", {"nav": "pages", "rows": rows, "kinds": KIND_LABELS})


@router.get("/pages/{item_id}")
def page_form(item_id: str, request: Request, con=Depends(user_required)):
    row = None
    if item_id != "new":
        row = con.execute("SELECT * FROM pages WHERE id = ?", (as_int(item_id),)).fetchone() or _404()
    kind = row["kind"] if row else ("article" if request.query_params.get("kind") == "article" else "page")
    articles = con.execute("SELECT slug FROM pages WHERE kind = 'articles'").fetchone()
    return page(request, "page_form.html", {
        "nav": "pages", "row": row, "kind": kind, "kind_label": KIND_LABELS[kind], "fixed": kind in FIXED_KINDS,
        "slug_prefix": (articles["slug"] + "/") if kind == "article" and articles and not row else "",
    })


@router.post("/pages/{item_id}")
async def page_save(item_id: str, request: Request, con=Depends(user_required)):
    form = await request.form()
    back = request.url.path
    row = con.execute("SELECT * FROM pages WHERE id = ?", (as_int(item_id),)).fetchone() if item_id != "new" else None
    kind = row["kind"] if row else ("article" if form.get("kind") == "article" else "page")
    if form.get("action") == "delete":
        if kind in FIXED_KINDS:
            return done(back, "固定頁面不能刪除，可以改成不發佈")
        con.execute("DELETE FROM pages WHERE id = ?", (row["id"],))
        con.commit()
        return done("/admin/pages/", "已刪除")
    try:
        slug = check_slug(form.get("slug"), allow_empty=(kind == "home"))
        if kind == "home":
            slug = ""
    except ValueError as e:
        return done(back, str(e))
    reserved = [u for tab, u in Q.tab_urls(con).items() if tab != "list"]
    if "/%s/" % slug in reserved:
        return done(back, "「/%s/」是演出頁分頁的網址，請換一個" % slug)
    data = {
        "slug": slug, "title": (form.get("title") or "").strip(), "title_en": (form.get("title_en") or "").strip(),
        "summary": (form.get("summary") or "").strip(), "summary_en": (form.get("summary_en") or "").strip(),
        "thumbnail_id": as_int(form.get("thumbnail_id")),
        "body_html": rich_value(form, "body_html", row["body_html"] if row else ""),
        "body_html_en": rich_value(form, "body_html_en", row["body_html_en"] if row else ""), "published": 1 if form.get("published") else 0,
        "published_at": form.get("published_at") or None,
        "sort_order": as_int(form.get("sort_order"), 0), "updated_at": db.now(),
    }
    if not data["title"]:
        return done(back, "請填標題")
    if kind in ("home",):
        data["published"] = 1
    cols = list(data)
    try:
        if not row:
            item_id = con.execute("INSERT INTO pages (kind, %s) VALUES (?, %s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                                  [kind] + [data[c] for c in cols]).lastrowid
        else:
            item_id = row["id"]
            con.execute("UPDATE pages SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                        [data[c] for c in cols] + [item_id])
            if row["slug"] != slug:
                add_redirects(con, Q.page_url(row), Q.page_url(data))
                navigation.rewrite_urls(con, Q.page_url(row), Q.page_url(data))
                if kind == "performances":      # 統計、歌單分頁在演出頁底下，一起轉
                    for sub in Q.TAB_SUBPATHS.values():
                        add_redirects(con, "/%s/%s/" % (row["slug"], sub), "/%s/%s/" % (slug, sub))
                if kind == "lyrics":       # 歌詞頁都在歌詞索引底下，一起轉
                    for l in con.execute("SELECT slug FROM lyrics"):
                        add_redirects(con, "/%s/%s/" % (row["slug"], l["slug"]), "/%s/%s/" % (slug, l["slug"]))
    except sqlite3.IntegrityError:
        return done(back, "網址「/%s/」已經有別的頁面在用" % slug)
    con.commit()
    return done("/admin/pages/%d" % item_id)


# ==================================================================== 圖片
def image_json(r):
    return {"id": r["id"], "title": r["title"], "width": r["width"], "height": r["height"],
            "thumb": Q.image_url(r["id"], 240), "url": Q.image_url(r["id"], 1200)}


@router.get("/images/")
def images_page(request: Request, con=Depends(user_required)):
    rows = con.execute("SELECT * FROM images ORDER BY id DESC").fetchall()
    return page(request, "images.html", {"nav": "images", "rows": rows})


@router.get("/api/images")
def images_api(request: Request, con=Depends(user_required)):
    q = request.query_params.get("q") or ""
    rows = con.execute("SELECT * FROM images WHERE title LIKE ? ORDER BY id DESC", ("%" + q + "%",)).fetchall()
    return [image_json(r) for r in rows]


ALLOWED_IMAGES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}


def store_upload(con, upload, title=""):
    from PIL import Image
    raw = upload.file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("%s 超過 20MB" % upload.filename)
    import io
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt, size = im.format, im.size
            im.verify()
    except Exception:
        raise ValueError("%s 不是圖片檔" % upload.filename)
    if fmt not in ALLOWED_IMAGES:
        raise ValueError("%s 的格式不支援（只收 JPG、PNG、WebP、GIF）" % upload.filename)
    base = slugify(os.path.splitext(upload.filename or "")[0]) or "image"
    name = "original_images/%s_%s%s" % (base[:40], secrets.token_hex(3), ALLOWED_IMAGES[fmt])
    path = os.path.join(db.MEDIA_ROOT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)
    title = title or os.path.splitext(upload.filename or "")[0]
    cur = con.execute("INSERT INTO images (file, title, width, height, created_at) VALUES (?, ?, ?, ?, ?)",
                      (name, title, size[0], size[1], db.now()))
    con.commit()
    return con.execute("SELECT * FROM images WHERE id = ?", (cur.lastrowid,)).fetchone()


@router.post("/api/images")
async def images_upload(request: Request, con=Depends(user_required)):
    form = await request.form()
    out, errors = [], []
    for upload in form.getlist("files"):
        try:
            out.append(image_json(store_upload(con, upload)))
        except ValueError as e:
            errors.append(str(e))
    return JSONResponse({"images": out, "errors": errors}, status_code=200 if out or not errors else 400)


@router.post("/images/{image_id}")
async def image_save(image_id: int, request: Request, con=Depends(user_required)):
    form = await request.form()
    row = con.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone() or _404()
    if form.get("action") == "delete":
        ref = "/images/%d/" % image_id
        used = con.execute("SELECT COUNT(*) FROM pages WHERE body_html LIKE ? OR body_html_en LIKE ?",
                           ("%" + ref + "%",) * 2).fetchone()[0]
        used += con.execute("SELECT COUNT(*) FROM lyrics WHERE intro_html LIKE ? OR sections_json LIKE ?",
                            ("%" + ref + "%",) * 2).fetchone()[0]
        if used and not form.get("force"):
            return done("/admin/images/", "這張圖還有 %d 個頁面的內文在用，確定要刪請勾「仍要刪除」" % used)
        con.execute("DELETE FROM images WHERE id = ?", (image_id,))
        con.commit()
        for path in [os.path.join(db.MEDIA_ROOT, row["file"])]:
            if os.path.isfile(path):
                os.remove(path)
        return done("/admin/images/", "已刪除")
    con.execute("UPDATE images SET title = ? WHERE id = ?", ((form.get("title") or "").strip(), image_id))
    con.commit()
    return done("/admin/images/")


# ==================================================================== 設定、轉址
SETTING_FIELDS = [
    ("網站", [("site_name", "網站名稱", "text"), ("site_name_en", "網站名稱（英文）", "text"),
              ("site_logo_id", "Logo（頁首左上角、瀏覽器分頁圖示）", "image",
               "建議用正方形、背景不透明的圖；會自動裁成正方形。空白就用內建的「163」圖示。")]),
    ("首頁", [("home_upcoming_count", "「即將演出」顯示幾場", "int"),
              ("home_top_songs_count", "「最近常唱」顯示幾首", "int"),
              ("home_top_songs_window", "「最近常唱」統計最近幾場有歌單的演出", "int"),
              ("home_facts_json", "數字卡片", "facts")]),
    ("演出頁：演出統計分頁", [("charts_intro_html", "說明文字", "rich"), ("charts_intro_html_en", "說明文字（英文）", "rich")]),
    ("演出頁：歌單統計分頁", [("setlist_intro_html", "說明文字", "rich"),
                      ("show_donation_call", "顯示捐款號召", "bool"),
                      ("donation_amount", "每份歌單捐款金額（新台幣）", "int"),
                      ("setlist_top_songs_count", "累積圖表預設顯示前幾名", "int")]),
    ("演出頁：年度回顧分頁", [("replay_intro_html", "說明文字", "rich"), ("replay_logo_id", "回顧卡片左上角的 Logo", "image")]),
]


def choices_of(field):
    """選單型設定欄位的選項：欄位定義第 3 個值之後、是 (值, 標籤) 的那些。"""
    return [c for c in field[2:] if isinstance(c, tuple)]


@router.get("/settings")
def settings_page(request: Request, con=Depends(user_required)):
    values = {f[0]: db.get_setting(con, f[0]) for _, fields in SETTING_FIELDS for f in fields}
    return page(request, "settings.html", {"nav": "settings", "groups": SETTING_FIELDS, "choices_of": choices_of, "values": values,
                                           "facts": json.loads(values["home_facts_json"] or "[]")})


@router.post("/settings")
async def settings_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    for _, fields in SETTING_FIELDS:
        for field in fields:
            key, kind = field[0], field[2]
            value = form.get(key) or ""
            if isinstance(kind, tuple):          # 選單：只收列出來的值
                value = value if value in [c[0] for c in choices_of(field)] else db.SETTINGS.get(key, "")
            elif kind == "rich":
                value = rich_value(form, key, db.get_setting(con, key))
            elif kind == "bool":
                value = "1" if value else "0"
            elif kind == "int":
                value = str(as_int(value, as_int(db.SETTINGS.get(key), 0)))
                if key == "home_hero_overlay":
                    value = str(min(100, max(0, int(value))))
            db.set_setting(con, key, value)
    con.commit()
    return done("/admin/settings")


# ==================================================================== 首頁大標題方框
HERO_KEYS = ("home_hero_image_id", "home_hero_mode", "home_hero_overlay", "home_hero_pos_x", "home_hero_pos_y",
             "home_hero_zoom")


@router.get("/hero")
def hero_page(request: Request, con=Depends(user_required)):
    home = con.execute("SELECT * FROM pages WHERE kind = 'home'").fetchone()
    links = [r for r in con.execute("SELECT * FROM pages WHERE kind IN ('performances', 'lyrics') AND published = 1 "
                                    "ORDER BY kind = 'lyrics'")]
    image_id = as_int(db.get_setting(con, "home_hero_image_id"))
    image = con.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone() if image_id else None
    return page(request, "hero.html", {
        "nav": "hero", "home": home, "links": links,
        "values": {k: db.get_setting(con, k) for k in HERO_KEYS},
        "image": image_json(image) if image else None,
    })


@router.post("/hero")
async def hero_save(request: Request, con=Depends(user_required)):
    form = await request.form()

    def clamp(key, lo, hi, default):
        try:
            return "%g" % round(min(hi, max(lo, float(form.get(key)))), 1)      # 70.0 存成 "70"
        except (TypeError, ValueError):
            return default
    db.set_setting(con, "home_hero_image_id", as_int(form.get("home_hero_image_id")) or "")
    db.set_setting(con, "home_hero_mode", form.get("home_hero_mode") if form.get("home_hero_mode") in ("cover", "side") else "cover")
    db.set_setting(con, "home_hero_overlay", clamp("home_hero_overlay", 0, 100, "70"))
    db.set_setting(con, "home_hero_pos_x", clamp("home_hero_pos_x", 0, 100, "50"))
    db.set_setting(con, "home_hero_pos_y", clamp("home_hero_pos_y", 0, 100, "50"))
    db.set_setting(con, "home_hero_zoom", clamp("home_hero_zoom", 100, 300, "100"))
    con.commit()
    return done("/admin/hero")


# ==================================================================== 頁首與頁尾
@router.get("/navigation")
def navigation_page(request: Request, con=Depends(user_required)):
    pages = [{"id": r["id"], "title": r["title"], "url": Q.page_url(r), "published": r["published"]}
             for r in con.execute("SELECT * FROM pages ORDER BY kind NOT IN ('home', 'performances', 'lyrics', "
                                  "'articles'), kind = 'article', sort_order, id")]
    return page(request, "navigation.html", {"nav": "navigation", "pages": pages,
                                             "header": navigation.load_header(con),
                                             "footer": navigation.load_footer(con)})


@router.post("/navigation")
async def navigation_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    # 兩個欄位都由頁面上的編輯器在送出時填入；空字串代表編輯器沒有載入，不能當成「全部清空」
    if not form.get("header_json") or not form.get("footer_json"):
        return done("/admin/navigation", "編輯器沒有正常載入，這次沒有存檔。請重新整理頁面再試。")
    try:
        header = json.loads(form["header_json"])
        footer = json.loads(form["footer_json"])
        assert isinstance(header, list) and isinstance(footer, dict)
    except (ValueError, AssertionError):
        return done("/admin/navigation", "資料讀不懂，請重新整理後再試")
    db.set_setting(con, navigation.HEADER_KEY, json.dumps(header, ensure_ascii=False))
    db.set_setting(con, navigation.FOOTER_KEY, json.dumps(footer, ensure_ascii=False))
    con.commit()
    return done("/admin/navigation")


@router.get("/redirects")
def redirects_page(request: Request, con=Depends(user_required)):
    rows = con.execute("SELECT * FROM redirects ORDER BY old_path").fetchall()
    return page(request, "redirects.html", {"nav": "redirects", "rows": rows})


@router.post("/redirects")
async def redirects_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    if form.get("delete"):
        con.execute("DELETE FROM redirects WHERE old_path = ?", (form["delete"],))
    else:
        old, new = (form.get("old_path") or "").strip(), (form.get("new_path") or "").strip()
        if not old.startswith("/") or not new:
            return done("/admin/redirects", "舊網址要以 / 開頭，新網址不能空白")
        if not old.endswith("/") and "." not in old.rsplit("/", 1)[-1]:
            old += "/"
        con.execute("INSERT OR REPLACE INTO redirects VALUES (?, ?)", (old, new))
    con.commit()
    return done("/admin/redirects")
