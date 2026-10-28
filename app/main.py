"""163braces 資訊站（FastAPI）。

    ./.venv/bin/uvicorn app.main:app --reload

前台網址跟舊站一樣：/performances/、/lyrics/泥潭的slug/、英文版前面加 /en。
頁面的網址存在 pages.slug，後台改了網址就會跟著變（並自動留下舊網址的轉址），
所以前台用一個萬用路由依 slug 找頁面，再依頁面種類（kind）決定版型。
"""
import json
import math
import os
from functools import partial

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import admin, auth, db, i18n, navigation, queries as Q, taiwan

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_VERSION = str(int(max(os.path.getmtime(os.path.join(HERE, "static", f))
                            for f in os.listdir(os.path.join(HERE, "static")))))


class LanguagePrefix:
    """/en/… → 路由看到的是 /…，語言放在 request.state.lang。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path, lang = scope["path"], "zh"
            if path == "/en" or path.startswith("/en/"):
                lang, path = "en", path[3:] or "/"
                scope = dict(scope, path=path, raw_path=path.encode())
            scope.setdefault("state", {})["lang"] = lang
        await self.app(scope, receive, send)


app = FastAPI(title="163braces", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(LanguagePrefix)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
app.include_router(admin.router)          # 要在下面的萬用路由之前
app.add_exception_handler(admin.LoginRequired, admin.login_redirect)
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.globals.update(image_url=Q.image_url, page_url=Q.page_url, song_cover_id=Q.song_cover_id,
                             asset_version=ASSET_VERSION, youtube_id=Q.youtube_id)


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


def render(request, con, name, ctx=None, status=200, page=None):
    lang = lang_of(request)
    path = request.url.path if lang == "zh" else "/en" + request.url.path
    alt = ("/en" + request.url.path) if lang == "zh" else request.url.path
    if request.url.query:
        alt += "?" + request.url.query
    kinds = Q.pages_by_kind(con)
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
        "current_path": path,
        "alt_url": alt,
        "page": page,
        "today": Q.today(),
    }
    context.update(ctx or {})
    return templates.TemplateResponse(request, name, context, status_code=status)


# ==================================================================== 圖片、雜項
@app.get("/media/{path:path}")
def media(path: str):
    full = os.path.realpath(os.path.join(db.MEDIA_ROOT, path))
    if not full.startswith(os.path.realpath(db.MEDIA_ROOT) + os.sep) or not os.path.isfile(full):
        raise HTTPException(404)
    return FileResponse(full, headers={"Cache-Control": "public, max-age=604800"})


IMAGE_WIDTHS = (120, 240, 400, 600, 800, 1200, 1600)


@app.get("/images/{image_id:int}/w{width:int}/")
def image(image_id: int, width: int, con=Depends(get_con)):
    """縮圖：第一次請求時用 Pillow 產生，存在 MEDIA_ROOT/cache/，之後直接回檔案。"""
    if width not in IMAGE_WIDTHS:
        raise HTTPException(404)
    row = con.execute("SELECT file FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    src = os.path.join(db.MEDIA_ROOT, row["file"])
    if not os.path.isfile(src):
        raise HTTPException(404)
    ext = os.path.splitext(src)[1].lower()
    ext = ext if ext in (".png", ".webp", ".gif") else ".jpg"
    cached = os.path.join(db.MEDIA_ROOT, "cache", "%d-w%d%s" % (image_id, width, ext))
    if not os.path.isfile(cached) or os.path.getmtime(cached) < os.path.getmtime(src):
        from PIL import Image, ImageOps
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            if ext == ".jpg" and im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            tmp = cached + ".tmp"
            im.save(tmp, format={".png": "PNG", ".webp": "WEBP", ".gif": "GIF"}.get(ext, "JPEG"), quality=85)
            os.replace(tmp, cached)
    return FileResponse(cached, headers={"Cache-Control": "public, max-age=2592000"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    return "User-agent: *\nAllow: /\nDisallow: /admin/\n\nSitemap: %s/sitemap.xml\n" % base


@app.get("/sitemap.xml")
def sitemap(request: Request, con=Depends(get_con)):
    base = str(request.base_url).rstrip("/")
    urls = [Q.page_url(p) for p in con.execute("SELECT slug FROM pages WHERE published = 1")]
    urls += [url for tab, url in Q.tab_urls(con).items() if tab != "list"]
    prefix = Q.lyrics_prefix(con)
    urls += [prefix + r["slug"] + "/" for r in con.execute("SELECT slug FROM lyrics WHERE published = 1")]
    body = "".join("<url><loc>%s%s</loc></url><url><loc>%s/en%s</loc></url>" % (base, u, base, u) for u in urls)
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % body,
                    media_type="application/xml")


ICON_SIZES = (32, 64, 180)


@app.get("/site-icon/{size:int}.png")
def site_icon(size: int, con=Depends(get_con)):
    """後台設定的 Logo 裁成正方形：分頁圖示（32）、頁首（64）、iPhone 加到主畫面（180）。"""
    logo = as_id(db.get_setting(con, "site_logo_id"))
    row = con.execute("SELECT file FROM images WHERE id = ?", (logo,)).fetchone() if logo else None
    src = os.path.join(db.MEDIA_ROOT, row["file"]) if row else ""
    if size not in ICON_SIZES or not os.path.isfile(src):
        return FileResponse(os.path.join(HERE, "static", "icon.svg"), media_type="image/svg+xml")
    cached = os.path.join(db.MEDIA_ROOT, "cache", "icon-%d-%d.png" % (logo, size))
    if not os.path.isfile(cached) or os.path.getmtime(cached) < os.path.getmtime(src):
        from PIL import Image, ImageOps
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGBA"), (size, size), Image.LANCZOS)
            im.save(cached + ".tmp", format="PNG")
        os.replace(cached + ".tmp", cached)
    return FileResponse(cached, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/favicon.ico")
def favicon(con=Depends(get_con)):
    return site_icon(32, con)


@app.get("/api/random-song", response_class=HTMLResponse)
def api_random_song(request: Request, exclude: int = 0, con=Depends(get_con)):
    """首頁「換一首」：回傳隨機聆聽區塊的 HTML。"""
    return render(request, con, "_listen.html", {"song": Q.random_song(con, exclude=exclude)})


# ==================================================================== 頁面
def home(request, con, page):
    n_up = int(db.get_setting(con, "home_upcoming_count") or 5)
    n_top = int(db.get_setting(con, "home_top_songs_count") or 5)
    window = int(db.get_setting(con, "home_top_songs_window") or 20)
    lang = lang_of(request)
    top, window_used = Q.top_songs(con, lang, n_top, window)
    upcoming = Q.upcoming(con, n_up)
    hero_image = as_id(db.get_setting(con, "home_hero_image_id"))
    return render(request, con, "home.html", {
        "hero_image": hero_image,
        "hero_mode": db.get_setting(con, "home_hero_mode") if hero_image else "",
        "hero_overlay": float(db.get_setting(con, "home_hero_overlay") or 0) / 100,
        "hero_x": float(db.get_setting(con, "home_hero_pos_x") or 50),
        "hero_y": float(db.get_setting(con, "home_hero_pos_y") or 50),
        "hero_zoom": float(db.get_setting(con, "home_hero_zoom") or 100) / 100,
        "upcoming": upcoming,
        "recent": [] if upcoming else Q.recent(con, 3),
        "top_songs": top,
        "top_window": window_used,
        "song": Q.random_song(con),
        "facts": json.loads(db.get_setting(con, "home_facts_json") or "[]"),
        "articles": Q.latest_articles(con, 3),
    }, page=page)


def month_groups(rows):
    groups = []
    for r in rows:
        key = r["event_date"][:7]
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(r)
    return groups


def performances_page(request, con, page, tab="list"):
    f = Q.parse_filters(request.query_params)
    rows = Q.performances(con, f)
    counts = Q.city_counts(con, f)
    cities = Q.cities(con)
    top = max(counts.values() or [1])
    map_cities = []
    for c in cities:
        n = counts.get(c["id"], 0)
        # 圓點面積跟場次成正比；沒有演出的縣市畫成小灰點
        map_cities.append(dict(c, n=n, r=round(4 + 9 * math.sqrt(n / top), 1) if n else 3))
    return render(request, con, "performances.html", dict(stats_context(request, con, tab), **{
        "f": f,
        "groups": month_groups(rows),
        "total": len(rows),
        "cities": cities,
        "types": Q.event_types(con),
        "map": taiwan.map_data(),
        "map_cities": map_cities,
        "filtered": any([f["q"], f["city"], f["event_type"], f["date_from"], f["date_to"]]),
    }), page=page)


TAB_TITLES = {"charts": "tab_charts", "setlist": "tab_setlist", "replay": "tab_replay"}


def stats_context(request, con, tab):
    """演出頁另外三個分頁（演出統計、歌單統計、年度回顧）的資料。分頁在瀏覽器端切換，所以每次都全部算好。

    年份參數都叫 year（跟舊站一樣，例如 /replay/?year=2025），只作用在目前打開的那個分頁。"""
    lang = lang_of(request)
    years = Q.available_years(con)
    this_year = Q.today()[:4]
    fallback = this_year if this_year in years else (years[0] if years else this_year)
    asked = request.query_params.get("year")
    year = asked if tab == "charts" and (asked == "all" or asked in years) else fallback
    ryear = asked if tab == "replay" and asked in years else fallback
    top_n = int(db.get_setting(con, "setlist_top_songs_count") or 10)
    song_all, song_top = Q.song_cumulative(con, lang, top_n)
    return {
        "tab": tab,
        "tab_urls": Q.tab_urls(con),
        "tab_title": i18n.t(lang, TAB_TITLES[tab]) if tab in TAB_TITLES else "",
        "years": years,
        "year": year,
        "ryear": ryear,
        "charts": Q.stats_charts(con, lang, year),
        "progress": Q.setlist_progress(con),
        "show_donation": db.get_setting(con, "show_donation_call") == "1",
        "donation_amount": db.get_setting(con, "donation_amount"),
        "setlist_intro": db.get_setting(con, "setlist_intro_html"),
        "replay_intro": db.get_setting(con, "replay_intro_html"),
        "song_all": song_all,
        "song_top": song_top,
        "top_n": top_n,
        "length_stats": Q.setlist_length_stats(con),
        "min_songs": Q.SETLIST_STATS_MIN_SONGS,
        "replay": Q.replay_data(con, ryear),
        "charts_intro": db.get_setting(con, "charts_intro_html_en" if lang == "en" else "charts_intro_html")
                        or db.get_setting(con, "charts_intro_html"),
    }


def lyrics_index(request, con, page):
    return render(request, con, "lyrics_index.html", {"boxes": Q.lyrics_boxes(con)}, page=page)


def lyrics_page(request, con, row):
    songs = con.execute(Q.SONG_SELECT + " WHERE g.lyrics_id = ? ORDER BY g.sort_order, g.id", (row["id"],)).fetchall()
    played, last = Q.song_play_stats(con, [s["id"] for s in songs])
    cover = next((Q.song_cover_id(s) for s in songs if Q.song_cover_id(s)), None)
    return render(request, con, "lyrics.html", {
        "lyr": row,
        "parts": Q.split_parts(json.loads(row["sections_json"])),
        "videos": json.loads(row["videos_json"]),
        "songs": songs,
        "cover": cover,
        "played": played,
        "last_played": last,
    }, page={"title": row["title"], "title_en": row["title_en"], "summary": "", "summary_en": "",
             "thumbnail_id": cover, "slug": ""})


def articles_page(request, con, page):
    rows = con.execute("SELECT * FROM pages WHERE kind = 'article' AND published = 1 "
                       "ORDER BY published_at DESC, id DESC").fetchall()
    return render(request, con, "articles.html", {"articles": rows}, page=page)


def content_page(request, con, page):
    return render(request, con, "page.html", {}, page=page)


HANDLERS = {"home": home, "performances": performances_page, "lyrics": lyrics_index,
            "articles": articles_page, "article": content_page, "page": content_page}


@app.get("/{path:path}")
def resolve(path: str, request: Request, con=Depends(get_con)):
    if path and not path.endswith("/"):
        url = request.url.path + "/" + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse(i18n.link(lang_of(request), url), status_code=301)
    slug = path.strip("/")
    # 未發佈的頁面只有登入後台的人看得到（預覽用）
    preview = bool(auth.current_user(con, request.cookies.get(auth.COOKIE)))
    page = con.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
    if page and (page["published"] or preview):
        return HANDLERS[page["kind"]](request, con, page)
    # 演出頁的統計、歌單、年度回顧分頁（各有自己的網址）
    for tab, url in Q.tab_urls(con).items():
        if tab != "list" and url == "/" + slug + "/":
            perf = Q.pages_by_kind(con).get("performances")
            if perf and (perf["published"] or preview):
                return performances_page(request, con, perf, tab)
    prefix = Q.lyrics_prefix(con).strip("/")
    if slug.startswith(prefix + "/") and "/" not in slug[len(prefix) + 1:]:
        row = con.execute("SELECT * FROM lyrics WHERE slug = ?", (slug[len(prefix) + 1:],)).fetchone()
        if row and (row["published"] or preview):
            return lyrics_page(request, con, row)
    raise HTTPException(404)


@app.exception_handler(StarletteHTTPException)
def not_found(request: Request, exc):
    if exc.status_code != 404:
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
    con = db.connect()
    try:
        lang = lang_of(request)
        full = ("/en" if lang == "en" else "") + request.url.path
        for candidate in (full, full.rstrip("/") + "/"):
            row = con.execute("SELECT new_path FROM redirects WHERE old_path = ?", (candidate,)).fetchone()
            if row:
                return RedirectResponse(row["new_path"], status_code=301)
        if request.url.path.startswith(("/images/", "/media/", "/static/")):
            return PlainTextResponse("Not found", status_code=404)
        return render(request, con, "404.html", {}, status=404)
    finally:
        con.close()
