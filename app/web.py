"""前台共用：模板、資料庫連線、語言、render()。

從 main.py 拆出來，讓其他前台路由（community.py 的粉絲功能）也能用同一個 render()，又不會循環 import。
"""
import os
import re
from functools import partial

from fastapi.templating import Jinja2Templates

from . import db, i18n, maps, navigation, queries as Q, visitors

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_VERSION = str(int(max(os.path.getmtime(os.path.join(HERE, "static", f))
                            for f in os.listdir(os.path.join(HERE, "static")))))

templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.globals.update(image_url=Q.image_url, page_url=Q.page_url, song_cover_id=Q.song_cover_id,
                             asset_version=ASSET_VERSION, youtube_id=Q.youtube_id)


def venue_url(p):
    """前台地點連到 Google 地圖：有原本的連結用連結，只有座標就用座標搜尋。"""
    if p["map_url"]:
        return p["map_url"]
    return maps.search_url(p["lat"], p["lng"]) if p["lat"] is not None else ""


templates.env.globals["venue_url"] = venue_url


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def as_id(value):
    return int(value) if str(value or "").isdigit() else None


def lang_of(request):
    return getattr(request.state, "lang", "zh")


def ga_id(con):
    """Google Analytics 的評估 ID：只在正式站載入；格式不對（例如貼錯成整段程式碼）就不放，免得插進奇怪的東西。"""
    value = (db.get_setting(con, "ga_measurement_id") or "").strip()
    return value if db.ON_AZURE and re.fullmatch(r"G-[A-Z0-9]{4,20}", value) else ""


def render(request, con, name, ctx=None, status=200, page=None):
    lang = lang_of(request)
    path = request.url.path if lang == "zh" else "/en" + request.url.path
    alt = ("/en" + request.url.path) if lang == "zh" else request.url.path
    if request.url.query:
        alt += "?" + request.url.query
    kinds = Q.pages_by_kind(con)
    visitor = current_visitor(request, con)
    context = {
        "request": request,
        "lang": lang,
        "t": partial(i18n.t, lang),
        "tr": partial(i18n.tr, lang),
        "link": partial(i18n.link, lang),
        "weekday": partial(i18n.weekday, lang),
        "ym_label": partial(i18n.ym_label, lang),
        "nav": navigation.header(con, lang, request.url.path),
        "footer": navigation.footer(con, lang),
        "kinds": kinds,
        "lyrics_prefix": Q.lyrics_prefix(con),
        "site_name": db.get_setting(con, "site_name_en" if lang == "en" else "site_name"),
        "logo_id": as_id(db.get_setting(con, "site_logo_id")),
        "ga_id": ga_id(con),
        "visitor": visitor,
        "guest": visitors.is_guest(visitor),          # 自取暱稱的臨時帳號：不能投稿
        "login_available": visitors.login_available(),
        "current_path": path,
        "alt_url": alt,
        "page": page,
        "today": Q.today(),
    }
    context.update(ctx or {})
    return templates.TemplateResponse(request, name, context, status_code=status)


def current_visitor(request, con):
    """目前登入的粉絲（沒登入是 None）。同一個請求只查一次。"""
    if not hasattr(request.state, "visitor"):
        request.state.visitor = visitors.current_visitor(con, request.cookies.get(visitors.COOKIE))
    return request.state.visitor
