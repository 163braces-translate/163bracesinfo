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
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, maps, navigation, pagetree, queries as Q, taiwan, visitors as V
from .web import ASSET_VERSION

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


def site_name():
    """後台分頁標題的後綴用網站名稱（「設定」→ 網站名稱）。"""
    con = db.connect()
    try:
        return db.get_setting(con, "site_name") or db.SETTINGS["site_name"]
    finally:
        con.close()


templates.env.globals["site_logo_id"] = site_logo_id
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.globals["site_name"] = site_name
templates.env.globals["maps_search"] = maps.search_url

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
        "pending": pending_counts(con),
        "sheet_delete_requests": con.execute("SELECT COUNT(*) FROM sheets WHERE delete_requested_at IS NOT NULL").fetchone()[0],
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

    data["map_url"], data["lat"], data["lng"], map_msg = performance_location(con, item_id, data, form.get("map_url"))

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
        return done("/admin/performances/new", map_msg or "已儲存")
    return done("/admin/performances/%d" % item_id, map_msg or "已儲存")


def performance_location(con, item_id, data, text):
    """演出存檔時的場地位置 → (連結, 緯度, 經度, 要提醒管理者的話)。
    連結沒改就沿用原本的座標（不用每次都去問 Google）；沒填的話，同一個場地以前填過就自動帶入。"""
    text = (text or "").strip()
    old = con.execute("SELECT map_url, lat, lng FROM performances WHERE id = ?", (as_int(item_id),)).fetchone()
    if not text:
        same = con.execute("SELECT map_url, lat, lng FROM performances WHERE venue = ? AND city_id = ? AND lat IS NOT NULL "
                           "ORDER BY event_date DESC LIMIT 1", (data["venue"], data["city_id"])).fetchone() \
            if data["venue"] else None
        return (same["map_url"], same["lat"], same["lng"], "已儲存，場地位置沿用同一個場地之前填的") if same \
            else ("", None, None, "")
    if old and old["map_url"] == text and old["lat"] is not None:
        return text, old["lat"], old["lng"], ""
    try:
        url, lat, lng = maps.resolve(text)
    except maps.MapLinkError as e:
        return text, None, None, "已儲存，但場地位置沒讀到：" + str(e)
    return url, lat, lng, far_warning(con, data["city_id"], lat, lng)


def far_warning(con, city_id, lat, lng):
    """座標離這場的縣市太遠（可能貼錯連結）就提醒；海外的城市沒有中心點，不檢查。"""
    city = con.execute("SELECT name, map_key FROM cities WHERE id = ?", (city_id,)).fetchone()
    center = city and taiwan.lonlat(city["map_key"])
    if not center:
        return ""
    km = taiwan.distance_km(center, (lng, lat))
    return "已儲存，但場地位置離%s的中心有 %d 公里，請確認連結有沒有貼錯" % (city["name"], km) if km > 60 else ""


# ==================================================================== 場地位置
def venue_rows(con, missing=False, q=""):
    """不重複的場地（地點名稱＋城市），附上目前的連結、有幾場已經有座標。"""
    rows = con.execute("""
        SELECT p.venue, p.city_id, c.name AS city_name, COUNT(*) AS n, MAX(p.event_date) AS last,
               SUM(p.lat IS NOT NULL) AS located,
               (SELECT x.map_url FROM performances x WHERE x.venue = p.venue AND x.city_id = p.city_id
                ORDER BY x.lat IS NULL, x.event_date DESC LIMIT 1) AS map_url,
               (SELECT x.lat || ', ' || x.lng FROM performances x WHERE x.venue = p.venue AND x.city_id = p.city_id
                AND x.lat IS NOT NULL ORDER BY x.event_date DESC LIMIT 1) AS coords
        FROM performances p JOIN cities c ON c.id = p.city_id
        WHERE p.venue != '' GROUP BY p.venue, p.city_id
        ORDER BY located = COUNT(*), MAX(p.event_date) DESC""").fetchall()
    return [r for r in rows if (not missing or r["located"] < r["n"]) and (not q or q.lower() in r["venue"].lower())]


@router.get("/venues")
def venues_page(request: Request, con=Depends(user_required)):
    return venues_render(request, con, {}, "")


def venues_render(request, con, results, summary):
    p = request.query_params
    all_rows = venue_rows(con)
    return page(request, "venues.html", {
        "nav": "venues", "rows": venue_rows(con, bool(p.get("missing")), (p.get("q") or "").strip()),
        "total": len(all_rows), "done": sum(1 for r in all_rows if r["located"] == r["n"]),
        "missing": bool(p.get("missing")), "q": p.get("q") or "", "results": results, "summary": summary,
    })


@router.post("/venues")
async def venues_save(request: Request, con=Depends(user_required)):
    """一次存很多個場地：只處理連結有改的，同一個場地（地點名稱＋城市）的每一場都套用。"""
    form = await request.form(max_fields=5000)
    changed = []
    for key, orig, text in zip(form.getlist("key"), form.getlist("orig"), form.getlist("map_url")):
        venue, _, city = key.rpartition("|")          # 城市 id 是數字，地點名稱裡有 | 也不會切錯
        if text.strip() != orig.strip():
            changed.append((venue, as_int(city), text.strip()))

    def look_up(item):
        if not item[2]:
            return item, ("", None, None), ""
        try:
            return item, maps.resolve(item[2]), ""
        except maps.MapLinkError as e:
            return item, (item[2], None, None), str(e)
    with ThreadPoolExecutor(max_workers=8) as pool:       # 短網址要問 Google，一起問比較快
        looked = list(pool.map(look_up, changed))

    results, ok = {}, 0
    for (venue, city_id, _), (url, lat, lng), error in looked:
        con.execute("UPDATE performances SET map_url = ?, lat = ?, lng = ? WHERE venue = ? AND city_id = ?",
                    (url, lat, lng, venue, city_id))
        warn = error or (far_warning(con, city_id, lat, lng).replace("已儲存，但", "") if lat is not None else "")
        if warn:
            results[(venue, city_id)] = warn
        elif lat is not None:
            ok += 1
    con.commit()
    summary = "更新了 %d 個場地" % len(looked) + ("，%d 個讀到座標" % ok if ok else "") \
        + ("，%d 個要再看一下（標紅色的）" % len(results) if results else "") if looked else "沒有變更"
    return venues_render(request, con, results, summary)


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
    if slug == Q.SHEETS_SEGMENT:
        return done(back, "「%s%s/」是樂譜分頁的網址，請換一個" % (Q.lyrics_prefix(con), slug))
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
        "sort_order": as_int(form.get("sort_order"), 0),
        "updated_at": db.now(),
    }
    if not data["title"]:
        return done(back, "請填曲名")
    if form.get("review_done"):
        data["review_json"] = "[]"
    status = db.status_after(form.get("action"), old_row["status"] if old_row else None, not old_row)
    data["status"], data["published"] = status, 1 if status == "live" else 0
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
    return done("/admin/lyrics/%d" % item_id, {"publish": "已發佈，前台看得到了", "unpublish": "已取消發佈，前台看不到了"}
                .get(form.get("action"), "已儲存" + ("（草稿，前台看不到）" if status == "draft" else "")))


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


def performance_tabs(con):
    """演出頁的四個分頁：(分頁, 名稱, 網址, 去哪裡編輯)。演出列表就是演出頁；另外三個不是 pages 表裡的頁面，
    有自己的編輯畫面（說明文字、參數、狀態），網址跟著演出頁走。"""
    perf = con.execute("SELECT id FROM pages WHERE kind = 'performances'").fetchone()
    urls = Q.tab_urls(con)
    return [("list", "演出列表", urls["list"], "/admin/pages/%d" % perf["id"] if perf else "/admin/pages/")] + \
        [(key, name, urls[key], "/admin/tabs/" + key) for key, name in TAB_NAMES.items()]


TAB_NAMES = {"charts": "演出統計", "setlist": "歌單統計", "replay": "年度回顧"}


@router.get("/pages/")
def pages_list(request: Request, con=Depends(user_required)):
    ids, urls = navigation.menu_refs(con)
    counts = {k: n for k, n in con.execute("SELECT status, COUNT(*) FROM pages GROUP BY status")}
    tab_status = Q.tab_statuses(con)
    for tab in TAB_NAMES:
        counts[tab_status[tab]] = counts.get(tab_status[tab], 0) + 1
    return page(request, "pages_list.html", {
        "nav": "pages", "nodes": pagetree.nested(con), "kinds": KIND_LABELS, "tabs": performance_tabs(con),
        "counts": counts, "tab_status": tab_status, "fixed_kinds": FIXED_KINDS,
        "articles_id": (con.execute("SELECT id FROM pages WHERE kind = 'articles'").fetchone() or [None])[0],
        "lyrics": con.execute("SELECT id, slug, title, status FROM lyrics ORDER BY sort_order, id").fetchall(),
        # 頁首或頁尾有沒有連到這一頁（用頁面或用自訂網址連都算）
        "in_menu": lambda p: p["id"] in ids or Q.page_url(p) in urls,
        "url_in_menu": lambda u: u in urls,
    })


@router.get("/pages/{item_id}")
def page_form(item_id: str, request: Request, con=Depends(user_required)):
    row = None
    if item_id != "new":
        row = con.execute("SELECT * FROM pages WHERE id = ?", (as_int(item_id),)).fetchone() or _404()
    if row:
        parent = con.execute("SELECT * FROM pages WHERE id = ?", (row["parent_id"],)).fetchone()
    else:
        # 新頁面：從樹狀列表按「＋子頁面」會帶 parent；沒帶就掛在首頁底下
        parent = con.execute("SELECT * FROM pages WHERE id = ?", (as_int(request.query_params.get("parent")),)).fetchone() \
            or con.execute("SELECT * FROM pages WHERE kind = 'home'").fetchone()
    if row:
        kind = row["kind"]
    elif request.query_params.get("kind") in ("article", "page"):
        kind = request.query_params["kind"]
    else:
        kind = "article" if parent and parent["kind"] in ("articles", "article") else "page"
    # 可以選的上層：除了自己和自己底下的頁面以外都可以
    blocked = {row["id"]} | {d["id"] for d in pagetree.descendants(con, row["id"])} if row else set()
    parents = [(p, depth) for p, depth in pagetree.tree(con) if p["id"] not in blocked]
    return page(request, "page_form.html", {
        "nav": "pages", "row": row, "kind": kind, "kind_label": KIND_LABELS[kind], "fixed": kind in FIXED_KINDS,
        "parent": parent, "parents": parents, "segment": pagetree.segment_of(row, parent) if row else "",
        "children": pagetree.has_children(con, row["id"]) if row else False,
        # 演出頁：列出底下的分頁（各自有編輯畫面）
        "tabs": performance_tabs(con) if kind == "performances" else [],
        "tab_status": Q.tab_statuses(con),
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
        if pagetree.has_children(con, row["id"]):
            return done(back, "這一頁底下還有子頁面，請先把它們搬到別的地方或刪除")
        con.execute("DELETE FROM pages WHERE id = ?", (row["id"],))
        con.commit()
        return done("/admin/pages/", "已刪除")
    # 網址＝上層頁面的網址＋這一段。首頁固定是 /，沒有上層
    if kind == "home":
        parent, segment = None, ""
    else:
        parent = con.execute("SELECT * FROM pages WHERE id = ?", (as_int(form.get("parent_id")),)).fetchone()
        if not parent:
            return done(back, "請選上層頁面")
        try:
            segment = check_slug(form.get("segment"), allow_slash=False)
        except ValueError as e:
            return done(back, str(e))
    slug = pagetree.join(parent["slug"] if parent else "", segment)
    reserved = [u for tab, u in Q.tab_urls(con).items() if tab != "list"]
    if "/%s/" % slug in reserved:
        return done(back, "「/%s/」是演出頁分頁的網址，請換一個" % slug)
    if "/%s/" % slug == Q.sheets_url(con):
        return done(back, "「/%s/」是歌詞頁「樂譜」分頁的網址，請換一個" % slug)
    data = {
        "title": (form.get("title") or "").strip(), "title_en": (form.get("title_en") or "").strip(),
        "summary": (form.get("summary") or "").strip(), "summary_en": (form.get("summary_en") or "").strip(),
        "thumbnail_id": as_int(form.get("thumbnail_id")),
        "body_html": rich_value(form, "body_html", row["body_html"] if row else ""),
        "body_html_en": rich_value(form, "body_html_en", row["body_html_en"] if row else ""),
        "published_at": form.get("published_at") or None,
        "sort_order": as_int(form.get("sort_order"), 0), "updated_at": db.now(),
    }
    if not data["title"]:
        return done(back, "請填標題")
    # 狀態由按下的按鈕決定（儲存／發佈／取消發佈）；首頁一定是線上
    status = "live" if kind == "home" else db.status_after(form.get("action"), row["status"] if row else None, not row)
    data["status"], data["published"] = status, 1 if status == "live" else 0
    cols = list(data)
    try:
        if not row:
            item_id = con.execute("INSERT INTO pages (kind, slug, parent_id, %s) VALUES (?, ?, ?, %s)"
                                  % (", ".join(cols), ", ".join("?" * len(cols))),
                                  [kind, slug, parent["id"] if parent else None] + [data[c] for c in cols]).lastrowid
        else:
            item_id = row["id"]
            con.execute("UPDATE pages SET %s WHERE id = ?" % ", ".join("%s = ?" % c for c in cols),
                        [data[c] for c in cols] + [item_id])
            if kind != "home" and (row["parent_id"] != parent["id"] or row["slug"] != slug):
                # 搬家或改網址：底下的頁面一起改，舊網址都轉到新網址
                pagetree.move(con, row, parent, segment, add_redirects)
    except pagetree.MoveError as e:
        con.rollback()
        return done(back, str(e))
    except sqlite3.IntegrityError:
        con.rollback()
        return done(back, "網址「/%s/」已經有別的頁面在用" % slug)
    con.commit()
    return done("/admin/pages/%d" % item_id, {"publish": "已發佈，前台看得到了", "unpublish": "已取消發佈，前台看不到了"}
                .get(form.get("action"), "已儲存" + ("（草稿，前台看不到）" if status == "draft" else "")))


@router.post("/pages/{page_id}/status")
async def page_status(page_id: int, request: Request, con=Depends(user_required)):
    """列表上的「發佈／取消發佈」快速按鈕：只改狀態，不動內容。"""
    form = await request.form()
    row = con.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
    action = form.get("action")
    if not row or row["kind"] == "home" or action not in ("publish", "unpublish"):
        return done("/admin/pages/", "首頁一直都在線上" if row and row["kind"] == "home" else "找不到這一頁")
    status = db.status_after(action, row["status"], False)
    con.execute("UPDATE pages SET status = ?, published = ?, updated_at = ? WHERE id = ?",
                (status, 1 if status == "live" else 0, db.now(), page_id))
    con.commit()
    return done("/admin/pages/", "「%s」%s" % (row["title"], "已發佈" if status == "live" else "已取消發佈"))


@router.get("/tabs/{tab}")
def tab_form(tab: str, request: Request, con=Depends(user_required)):
    """演出頁分頁（演出統計、歌單統計、年度回顧）的編輯畫面：狀態、說明文字與參數。"""
    if tab not in TAB_NAMES:
        _404()
    perf = con.execute("SELECT * FROM pages WHERE kind = 'performances'").fetchone()
    group = PERF_TAB_SETTINGS[tab]
    return page(request, "tab_form.html", {
        "nav": "pages", "tab": tab, "name": TAB_NAMES[tab], "url": Q.tab_urls(con)[tab], "perf": perf,
        "row": {"status": Q.tab_statuses(con)[tab]},
        "groups": [group], "values": setting_values(con, [group]), "choices_of": choices_of,
    })


@router.post("/tabs/{tab}")
async def tab_save(tab: str, request: Request, con=Depends(user_required)):
    if tab not in TAB_NAMES:
        _404()
    form = await request.form()
    action = form.get("action")
    status = db.status_after(action, Q.tab_statuses(con)[tab], False)
    db.set_setting(con, "tab_status_" + tab, status)
    save_setting_groups(con, form, [PERF_TAB_SETTINGS[tab]])
    con.commit()
    return done("/admin/tabs/" + tab, {"publish": "已發佈，前台看得到了", "unpublish": "已取消發佈，前台看不到了"}
                .get(action, "已儲存"))


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
    ("首頁要顯示的區塊", [("home_show_marquee", "粉絲留言跑馬燈", "bool"),
                   ("home_show_upcoming", "即將演出", "bool"),
                   ("home_show_top_songs", "最近常唱", "bool"),
                   ("home_show_listen", "隨機聆聽", "bool"),
                   ("home_show_facts", "數字卡片（例如 YouTube 訂閱數）", "bool"),
                   ("home_show_articles", "最新文章", "bool")]),
    ("首頁", [("home_marquee_speed", "跑馬燈速度（每秒捲動幾像素，最少 10）", "int", "數字越大越快，預設 70。"),
              ("home_upcoming_count", "「即將演出」顯示幾場", "int"),
              ("home_recent_count", "沒有即將演出時，改列幾場「最近的演出」", "int", "填 0 就只顯示「目前沒有已公布的演出」。"),
              ("home_top_songs_count", "「最近常唱」顯示幾首", "int"),
              ("home_top_songs_window", "「最近常唱」統計最近幾場有歌單的演出", "int"),
              ("home_facts_json", "數字卡片", "facts")]),
]

# 演出頁三個分頁各自的設定：在各分頁的編輯畫面（/admin/tabs/<分頁>）改，跟分頁的狀態一起存
PERF_TAB_SETTINGS = {
    "charts": ("說明與設定", [("charts_intro_html", "說明文字", "rich"), ("charts_intro_html_en", "說明文字（英文）", "rich")]),
    "setlist": ("說明與設定", [("setlist_intro_html", "說明文字", "rich"),
                    ("show_donation_call", "顯示捐款號召", "bool"),
                    ("donation_amount", "每份歌單捐款金額（新台幣）", "int"),
                    ("setlist_top_songs_count", "累積圖表預設顯示前幾名", "int"),
                    ("setlist_prob_window", "演出機率對照表：左邊預設看最近幾場", "int",
                     "訪客可以自己改場數。只算有歌單、已經發生的演出。")]),
    "replay": ("說明與設定", [("replay_intro_html", "說明文字", "rich"), ("replay_logo_id", "回顧卡片左上角的 Logo", "image")]),
}


def setting_values(con, groups):
    return {f[0]: db.get_setting(con, f[0]) for _, fields in groups for f in fields}


def save_setting_groups(con, form, groups):
    """把表單裡的這些設定欄位存起來（「設定」頁、演出頁分頁的編輯畫面共用）。"""
    for _, fields in groups:
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
                if key == "home_marquee_speed":
                    value = str(max(10, int(value)))
            db.set_setting(con, key, value)


def choices_of(field):
    """選單型設定欄位的選項：欄位定義第 3 個值之後、是 (值, 標籤) 的那些。"""
    return [c for c in field[2:] if isinstance(c, tuple)]


@router.get("/settings")
def settings_page(request: Request, con=Depends(user_required)):
    values = setting_values(con, SETTING_FIELDS)
    return page(request, "settings.html", {"nav": "settings", "groups": SETTING_FIELDS, "choices_of": choices_of,
                                           "values": values,
                                           "facts": json.loads(values["home_facts_json"] or "[]")})


@router.post("/settings")
async def settings_save(request: Request, con=Depends(user_required)):
    form = await request.form()
    save_setting_groups(con, form, SETTING_FIELDS)
    con.commit()
    return done("/admin/settings")


# ==================================================================== 粉絲投稿的審核
def _visitor_label(row):
    return (row["nickname"] or row["google_name"] or "（已刪除的帳號）") + ("（已停權）" if row["banned"] else "")


# 投稿審核頁的四種投稿：上面「待審核」、下面「已審核」各列一次
REVIEW_KINDS = [("contributions", "歌單"), ("shows", "新演出"), ("sheets", "樂譜"), ("marquee", "跑馬燈")]


def review_rows(con, kind, pending, limit):
    """某一種投稿的待審核（pending=True）或已審核的列。樂譜的「要求刪除」算待審核；跑馬燈是管理者還沒看過的算待審核。"""
    if kind == "contributions":
        return con.execute("""
            SELECT c.*, p.event_date, p.event_name, v.nickname, v.google_name, v.banned
            FROM contributions c JOIN performances p ON p.id = c.performance_id LEFT JOIN visitors v ON v.id = c.visitor_id
            WHERE c.status %s 'pending' ORDER BY c.created_at DESC LIMIT ?""" % ("=" if pending else "!="), (limit,)).fetchall()
    if kind == "shows":
        return [dict(r, **json.loads(r["payload_json"])) for r in con.execute("""
            SELECT s.*, v.nickname, v.google_name, v.banned FROM show_submissions s LEFT JOIN visitors v ON v.id = s.visitor_id
            WHERE s.status %s 'pending' ORDER BY s.created_at DESC LIMIT ?""" % ("=" if pending else "!="), (limit,))]
    if kind == "sheets":
        where = ("s.status = 'pending' OR s.delete_requested_at IS NOT NULL" if pending
                 else "s.status != 'pending' AND s.delete_requested_at IS NULL")
        return con.execute("""
            SELECT s.*, g.title AS song_title, v.nickname, v.google_name, v.banned
            FROM sheets s JOIN songs g ON g.id = s.song_id LEFT JOIN visitors v ON v.id = s.visitor_id
            WHERE %s ORDER BY COALESCE(s.delete_requested_at, s.created_at) DESC LIMIT ?""" % where, (limit,)).fetchall()
    return con.execute("""
        SELECT m.*, v.nickname, v.google_name, v.banned FROM marquee_posts m JOIN visitors v ON v.id = m.visitor_id
        WHERE m.reviewed_at IS %s ORDER BY m.created_at DESC LIMIT ?""" % ("NULL" if pending else "NOT NULL"), (limit,)).fetchall()


def pending_counts(con):
    return {
        "contributions": con.execute("SELECT COUNT(*) FROM contributions WHERE status = 'pending'").fetchone()[0],
        "shows": con.execute("SELECT COUNT(*) FROM show_submissions WHERE status = 'pending'").fetchone()[0],
        "sheets": con.execute("SELECT COUNT(*) FROM sheets WHERE status = 'pending' OR delete_requested_at IS NOT NULL").fetchone()[0],
        "marquee": con.execute("SELECT COUNT(*) FROM marquee_posts WHERE reviewed_at IS NULL").fetchone()[0],
    }


@router.get("/submissions")
def submissions(request: Request, con=Depends(user_required)):
    return page(request, "submissions.html", {
        "nav": "submissions", "kinds": REVIEW_KINDS, "label": _visitor_label,
        "pending": {k: review_rows(con, k, True, 500) for k, _ in REVIEW_KINDS},
        "reviewed": {k: review_rows(con, k, False, 50) for k, _ in REVIEW_KINDS},
    })


def _apply_setlist(con, performance_id, items):
    """投稿的歌單（payload 裡的 setlist）取代這場演出的歌單。曲庫裡已經刪掉的歌改存成自訂曲名。"""
    known = {r[0] for r in con.execute("SELECT id FROM songs")}
    rows = [(it["song_id"] if it["song_id"] in known else None,
             "" if it["song_id"] in known else (it["custom_title"] or "?"), it.get("note") or "")
            for it in items]
    con.execute("DELETE FROM setlist_items WHERE performance_id = ?", (performance_id,))
    con.executemany("INSERT INTO setlist_items (performance_id, position, song_id, custom_title, note) "
                    "VALUES (?, ?, ?, ?, ?)", [(performance_id, i) + r for i, r in enumerate(rows)])


def _setlist_lines(con, items):
    """歌單（setlist_items 的列，或投稿的 payload）→ 顯示用的文字列。"""
    names = {r["id"]: r["title"] for r in con.execute("SELECT id, title FROM songs")}
    out = []
    for it in items:
        title = names.get(it["song_id"], "?") if it["song_id"] else it["custom_title"] + "（自訂）"
        out.append(title + ("｜" + it["note"] if it["note"] else ""))
    return out


@router.get("/submissions/contribution/{item_id:int}")
def contribution_detail(item_id: int, request: Request, con=Depends(user_required)):
    c = con.execute("SELECT c.*, v.nickname, v.google_name, v.banned, v.email FROM contributions c "
                    "LEFT JOIN visitors v ON v.id = c.visitor_id WHERE c.id = ?", (item_id,)).fetchone() or _404()
    perf = con.execute(Q.PERF_SELECT + " WHERE p.id = ?", (c["performance_id"],)).fetchone()
    payload = json.loads(c["payload_json"])
    fields = [(f, label, perf[f], payload[f]) for f, label in
              [("event_name", "活動名稱"), ("event_name_en", "英文名稱"), ("venue", "地點"), ("venue_en", "英文地點")]
              if f in payload]
    current = con.execute("SELECT * FROM setlist_items WHERE performance_id = ? ORDER BY position, id",
                          (perf["id"],)).fetchall()
    return page(request, "contribution_detail.html", {
        "nav": "submissions", "c": c, "perf": perf, "payload": payload, "fields": fields, "label": _visitor_label(c),
        "setlist_old": _setlist_lines(con, current),
        "setlist_new": _setlist_lines(con, payload["setlist"]) if "setlist" in payload else None,
    })


@router.post("/submissions/contribution/{item_id:int}")
async def contribution_review(item_id: int, request: Request, con=Depends(user_required)):
    form = await request.form()
    c = con.execute("SELECT * FROM contributions WHERE id = ?", (item_id,)).fetchone() or _404()
    note = (form.get("admin_note") or "").strip()[:500]
    if c["status"] != "pending":
        return done("/admin/submissions/contribution/%d" % item_id, "這筆已經處理過了")
    if form.get("action") == "approve":
        payload = json.loads(c["payload_json"])
        cols = [f for f in ("event_name", "event_name_en", "venue", "venue_en") if f in payload]
        if "event_name" in cols and not payload["event_name"].strip():
            return done("/admin/submissions/contribution/%d" % item_id, "活動名稱不能是空白，不能直接套用")
        if cols:
            con.execute("UPDATE performances SET %s WHERE id = ?" % ", ".join("%s = ?" % f for f in cols),
                        [payload[f] for f in cols] + [c["performance_id"]])
        if "setlist" in payload:
            _apply_setlist(con, c["performance_id"], payload["setlist"])
        status, msg = "approved", "已套用到演出資料"
    elif form.get("action") == "reject":
        status, msg = "rejected", "已退回"
    else:
        return done("/admin/submissions/contribution/%d" % item_id, "沒有變更")
    con.execute("UPDATE contributions SET status = ?, admin_note = ?, reviewed_at = ? WHERE id = ?",
                (status, note, db.now(), item_id))
    con.commit()
    return done("/admin/submissions", msg)


@router.get("/submissions/show/{item_id:int}")
def show_submission_detail(item_id: int, request: Request, con=Depends(user_required)):
    s = con.execute("SELECT s.*, v.nickname, v.google_name, v.banned, v.email FROM show_submissions s "
                    "LEFT JOIN visitors v ON v.id = s.visitor_id WHERE s.id = ?", (item_id,)).fetchone() or _404()
    payload = json.loads(s["payload_json"])
    return page(request, "show_submission_detail.html", {
        "nav": "submissions", "s": s, "p": payload, "label": _visitor_label(s),
        "setlist": _setlist_lines(con, payload.get("setlist") or []),
        "types": Q.event_types(con), "cities": Q.cities(con),
        # 同一天已經有的演出：避免重複新增
        "same_day": con.execute(Q.PERF_SELECT + " WHERE p.event_date = ?", (payload["event_date"],)).fetchall(),
    })


@router.post("/submissions/show/{item_id:int}")
async def show_submission_review(item_id: int, request: Request, con=Depends(user_required)):
    """核准：用管理者在審核畫面改過的內容新增一場演出；退回：只記錄原因。"""
    form = await request.form()
    s = con.execute("SELECT * FROM show_submissions WHERE id = ?", (item_id,)).fetchone() or _404()
    back = "/admin/submissions/show/%d" % item_id
    if s["status"] != "pending":
        return done(back, "這筆已經處理過了")
    note = (form.get("admin_note") or "").strip()[:500]
    if form.get("action") == "reject":
        con.execute("UPDATE show_submissions SET status = 'rejected', admin_note = ?, reviewed_at = ? WHERE id = ?",
                    (note, db.now(), item_id))
        con.commit()
        return done("/admin/submissions", "已退回")
    if form.get("action") != "approve":
        return done(back, "沒有變更")
    data = {f: (form.get(f) or "").strip()[:255] for f in ("event_date", "event_name", "event_name_en", "venue", "venue_en")}
    data["event_type_id"], data["city_id"] = as_int(form.get("event_type_id")), as_int(form.get("city_id"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["event_date"]) or not data["event_name"]:
        return done(back, "日期與活動名稱要填")
    if not con.execute("SELECT 1 FROM event_types WHERE id = ?", (data["event_type_id"],)).fetchone() \
            or not con.execute("SELECT 1 FROM cities WHERE id = ?", (data["city_id"],)).fetchone():
        return done(back, "請選類型與城市")
    data["map_url"], data["lat"], data["lng"], map_msg = performance_location(con, None, data, form.get("map_url"))
    cols = list(data)
    perf_id = con.execute("INSERT INTO performances (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                          [data[c] for c in cols]).lastrowid
    payload = json.loads(s["payload_json"])
    if payload.get("setlist"):
        _apply_setlist(con, perf_id, payload["setlist"])
    con.execute("UPDATE show_submissions SET status = 'approved', admin_note = ?, performance_id = ?, reviewed_at = ? "
                "WHERE id = ?", (note, perf_id, db.now(), item_id))
    con.commit()
    return done("/admin/performances/%d" % perf_id, "已加入演出列表，可以在這裡繼續補資料"
                + ("。" + map_msg.replace("已儲存，", "") if map_msg else ""))


@router.get("/submissions/sheet/{item_id:int}")
def sheet_detail(item_id: int, request: Request, con=Depends(user_required)):
    s = con.execute("SELECT s.*, g.title AS song_title, v.nickname, v.google_name, v.banned, v.email FROM sheets s "
                    "JOIN songs g ON g.id = s.song_id LEFT JOIN visitors v ON v.id = s.visitor_id WHERE s.id = ?",
                    (item_id,)).fetchone() or _404()
    files = con.execute("SELECT * FROM sheet_files WHERE sheet_id = ? ORDER BY position", (item_id,)).fetchall()
    return page(request, "sheet_detail.html", {"nav": "submissions", "s": s, "files": files, "label": _visitor_label(s)})


@router.post("/submissions/sheet/{item_id:int}")
async def sheet_review(item_id: int, request: Request, con=Depends(user_required)):
    form = await request.form()
    con.execute("SELECT 1 FROM sheets WHERE id = ?", (item_id,)).fetchone() or _404()
    # 投稿者要求刪除：整份刪掉（圖檔一起），或不刪（清掉要求，可以寫原因）
    if form.get("action") == "delete":
        V.delete_sheet(con, item_id)
        return done("/admin/submissions", "已刪除這份樂譜")
    if form.get("action") == "keep":
        con.execute("UPDATE sheets SET delete_requested_at = NULL, admin_note = ? WHERE id = ?",
                    ((form.get("admin_note") or "").strip()[:500], item_id))
        con.commit()
        return done("/admin/submissions/sheet/%d" % item_id, "已保留，投稿者可以再要求一次")
    status = {"approve": "approved", "reject": "rejected", "remove": "removed", "restore": "approved"}.get(form.get("action"))
    if not status:
        return done("/admin/submissions/sheet/%d" % item_id, "沒有變更")
    row = con.execute("SELECT * FROM sheets WHERE id = ?", (item_id,)).fetchone()
    if status == "approved" and row["replaces_id"]:
        # 修改版通過：內容搬進原本那份（網址 /sheets/<id>/ 和讚數不變），修改版那筆刪掉
        orig = row["replaces_id"]
        old_files = [r["file"] for r in con.execute("SELECT file FROM sheet_files WHERE sheet_id = ?", (orig,))]
        con.execute("UPDATE sheets SET title = ?, text_body = ?, video_url = ?, name_mode = ?, status = 'approved', "
                    "admin_note = ?, reviewed_at = ? WHERE id = ?",
                    (row["title"], row["text_body"], row["video_url"], row["name_mode"],
                     (form.get("admin_note") or "").strip()[:500], db.now(), orig))
        con.execute("DELETE FROM sheet_files WHERE sheet_id = ?", (orig,))
        con.execute("UPDATE sheet_files SET sheet_id = ? WHERE sheet_id = ?", (orig, item_id))
        con.execute("DELETE FROM sheets WHERE id = ?", (item_id,))
        con.commit()
        V.remove_unused_media(con, old_files)
        return done("/admin/submissions/sheet/%d" % orig, "修改版已套用到公開的樂譜")
    con.execute("UPDATE sheets SET status = ?, admin_note = ?, reviewed_at = ? WHERE id = ?",
                (status, (form.get("admin_note") or "").strip()[:500], db.now(), item_id))
    con.commit()
    return done("/admin/submissions/sheet/%d" % item_id, {"approved": "已公開", "rejected": "已退回", "removed": "已下架"}[status])


# ==================================================================== 跑馬燈與粉絲帳號
@router.get("/marquee")
def marquee_admin(request: Request, con=Depends(user_required)):
    rows = con.execute("SELECT m.*, v.nickname, v.google_name, v.banned FROM marquee_posts m "
                       "JOIN visitors v ON v.id = m.visitor_id ORDER BY m.created_at DESC LIMIT 300").fetchall()
    return page(request, "marquee.html", {"nav": "marquee", "rows": rows, "label": _visitor_label})


@router.post("/marquee")
async def marquee_action(request: Request, con=Depends(user_required)):
    form = await request.form()
    post_id, action = as_int(form.get("id")), form.get("action")
    if action in ("hide", "show"):
        con.execute("UPDATE marquee_posts SET hidden = ?, reviewed_at = COALESCE(reviewed_at, ?) WHERE id = ?",
                    (1 if action == "hide" else 0, db.now(), post_id))
    elif action == "ok":
        con.execute("UPDATE marquee_posts SET reviewed_at = ? WHERE id = ?", (db.now(), post_id))
    elif action == "delete":
        con.execute("DELETE FROM marquee_posts WHERE id = ?", (post_id,))
    con.commit()
    back = form.get("back") or ""
    return done(back if back.startswith("/admin/") else "/admin/marquee")


@router.get("/visitors")
def visitors_admin(request: Request, con=Depends(user_required)):
    rows = con.execute("""
        SELECT v.*,
          (SELECT COUNT(*) FROM attendance a WHERE a.visitor_id = v.id) AS n_attend,
          (SELECT COUNT(*) FROM marquee_posts m WHERE m.visitor_id = v.id) AS n_marquee,
          (SELECT COUNT(*) FROM contributions c WHERE c.visitor_id = v.id) AS n_contrib,
          (SELECT COUNT(*) FROM sheets s WHERE s.visitor_id = v.id) AS n_sheets
        FROM visitors v ORDER BY v.created_at DESC""").fetchall()
    return page(request, "visitors.html", {"nav": "visitors", "rows": rows})


@router.post("/visitors")
async def visitors_action(request: Request, con=Depends(user_required)):
    form = await request.form()
    vid = as_int(form.get("id"))
    if form.get("action") in ("ban", "unban"):
        con.execute("UPDATE visitors SET banned = ? WHERE id = ?", (1 if form.get("action") == "ban" else 0, vid))
        con.commit()
    back = form.get("back") if (form.get("back") or "").startswith("/admin/") else "/admin/visitors"
    return done(back, "已停權（不能再投稿，跑馬燈也不再顯示）" if form.get("action") == "ban" else "已恢復")


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
    # 演出頁的分頁不是 pages 表裡的頁面，另外列出來讓選單可以直接選
    targets = [{"label": name, "url": url} for key, name, url, _ in performance_tabs(con) if key != "list"]
    return page(request, "navigation.html", {"nav": "navigation", "pages": pages, "targets": targets,
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
