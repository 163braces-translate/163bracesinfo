"""相簿 /photos/：粉絲上傳現場照片，跟演出資料串在一起。

- 相簿首頁 /photos/：「合照」置頂，接著是演出相簿（一場一本）、自訂相簿
- 一場演出的所有照片 /photos/show/<演出 id>/：本場相簿、合照、其他相簿裡標了這場的照片、連結到這場的自訂相簿
  （演出列表上的 📷 連到這裡）
- 合照 /photos/group/：依場次分段；只有這裡能傳影片、貼 YouTube
- 自訂相簿 /photos/<id>/

權限：要用 Google 帳號登入才能上傳（訪客、停權的不行，跟其他投稿一樣）。任何人都可以建自訂相簿、
上傳到任何一本相簿（包括別人建的）。照片只有上傳的人能刪、能改說明與對應的場次；自訂相簿的標題與
整本連結的場次由建立的人改。管理者在後台只能「下架」（status＝removed），不能刪；下架的照片上傳的人
自己還看得到，旁邊註明原因。

照片在伺服器重新編碼成 JPEG（去掉 GPS 等拍攝資訊），最長邊 2400px；瀏覽器上傳前會先縮（album.js），
省流量也省 /home 的空間。縮圖第一次被看時才產生，存在 MEDIA_ROOT/cache/photos/。
"""
import io
import os
import secrets
import shutil
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import auth, db, i18n, pagecache, queries as Q, visitors as V
from .community import T, check_post, closed, is_admin, login_url, submit_block
from .web import as_id, current_visitor, get_con, lang_of, render



# 相簿關閉時，上傳的人還是可以在「我的投稿」看自己的照片、刪掉（隱私權政策承諾的）：這幾個路由對本人開放
OWNER_ROUTES = ("/photos/img/{photo_id:int}/{size}.jpg", "/photos/video/{photo_id:int}", "/photos/photo/{photo_id:int}/delete")


def album_open(request: Request, con=Depends(get_con)):
    """相簿頁在後台「頁面與文章」取消發佈：整個相簿區（含照片檔）都 404。
    例外：登入後台的管理者照樣看得到（方便預覽）；上傳的人看得到、刪得掉自己的照片。"""
    if db.album_published(con) or is_admin(request, con):
        return
    route = request.scope.get("route")
    if route is not None and route.path in OWNER_ROUTES:
        visitor = current_visitor(request, con)
        pid = request.path_params.get("photo_id")
        if visitor and con.execute("SELECT 1 FROM photos WHERE id = ? AND visitor_id = ?", (pid, visitor["id"])).fetchone():
            return
    raise HTTPException(404)


router = APIRouter(dependencies=[Depends(album_open)])

MAX_ITEMS = 20                          # 一次最多幾張（含影片、YouTube）
PHOTO_MAX_BYTES = 15 * 1024 * 1024      # 瀏覽器沒縮到的原檔上限（有 JavaScript 時會先縮到 2–3MB）
PHOTO_MAX_SIDE = 2400
VIDEO_MAX_BYTES = 80 * 1024 * 1024
UPLOAD_MAX_BYTES = 200 * 1024 * 1024    # 一次上傳的總大小（手機網路傳太久容易斷；也不讓一次塞爆暫存空間）
VIDEO_DAILY = 5                         # 每人每 24 小時最多幾支影片（影片最佔空間）
# 儲存空間：Azure B1 方案的 /home 共 10GB，資料庫、備份、上傳的檔案、網站程式、記錄檔都算在內。
# 剩不到 STORAGE_RESERVE 就暫停收上傳（留給資料庫繼續寫入；網站程式與記錄檔也在這 1.5GB 裡）。
STORAGE_QUOTA = 10 * 1024 ** 3 if db.ON_AZURE else None
STORAGE_RESERVE = int(1.5 * 1024 ** 3)
VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
SIZES = {"s": 600, "l": 1600}           # 縮圖（格子）、大圖（點開看）；o＝原檔
TITLE_MAX = 60
CAPTION_MAX = 200


def _404():
    raise HTTPException(404)


def prefix(request):
    return "/en" if lang_of(request) == "en" else ""


# ==================================================================== 資料
ALBUM_SLUG = "photos"       # 相簿頁的網址固定是 /photos/（底下的演出相簿、合照等網址都寫在這個檔案的路由裡）
# 不用 /album/：音樂人的網站上 album 會被當成「專輯」，英文訪客、搜尋引擎都會誤會，也留給以後可能的專輯頁


def ensure_album_page(con):
    """相簿頁（pages 表 kind='album'）：後台「頁面與文章」裡的固定頁面，可以改標題、介紹、摘要、縮圖、發佈狀態。
    啟動時沒有就建立，掛在首頁底下，內容用原本寫在程式裡的文字。"""
    if con.execute("SELECT 1 FROM pages WHERE kind = 'album'").fetchone():
        return
    home = con.execute("SELECT id FROM pages WHERE kind = 'home'").fetchone()
    if con.execute("SELECT 1 FROM pages WHERE slug = ?", (ALBUM_SLUG,)).fetchone():
        print("相簿頁沒有建立：網址 /%s/ 已經有別的頁面在用" % ALBUM_SLUG)
        return
    try:
        con.execute("INSERT INTO pages (kind, parent_id, slug, title, title_en, summary, summary_en, body_html, body_html_en, "
                    "published, status, sort_order, updated_at) VALUES ('album', ?, ?, '相簿', 'Photos', ?, ?, ?, ?, 1, 'live', 0, ?)",
                    (home["id"] if home else None, ALBUM_SLUG,
                     "粉絲分享的 163braces 演出現場照片、合照與影片。", "Photos, group shots and videos from 163braces shows, shared by fans.",
                     intro_html(con, "zh"), intro_html(con, "en"), db.now()))
        con.commit()
    except db.sqlite3.IntegrityError:        # 另一個 worker 剛好同時建好了
        con.rollback()


def intro_html(con, lang):
    """相簿頁的預設內文：介紹＋轉載聲明。之後在後台「頁面與文章 → 相簿」改。"""
    email = db.get_setting(con, "contact_email")
    return "<p>%s</p><p><small>%s</small></p>" % (
        i18n.t(lang, "album_intro"), i18n.t(lang, "album_rights" if email else "album_rights_plain", email=email))


def album_page(con):
    return con.execute("SELECT * FROM pages WHERE kind = 'album'").fetchone()


def ensure_group_album(con):
    """「合照」相簿全站一本，啟動時沒有就建立。"""
    if not con.execute("SELECT 1 FROM photo_albums WHERE kind = 'group'").fetchone():
        con.execute("INSERT INTO photo_albums (kind, title, title_en, created_at, updated_at) "
                    "VALUES ('group', '合照', 'Group photos', ?, ?)", (db.now(), db.now()))
        con.commit()


def group_album(con):
    ensure_group_album(con)
    return con.execute("SELECT * FROM photo_albums WHERE kind = 'group'").fetchone()


def album_url(album):
    if album["kind"] == "group":
        return "/photos/group/"
    if album["kind"] == "show" and album["performance_id"]:
        return "/photos/show/%d/" % album["performance_id"]
    return "/photos/%d/" % album["id"]


def drop_empty_albums(con):
    """演出相簿、自訂相簿的照片都刪光了就整本刪掉（合照留著）。呼叫的人負責 commit。"""
    con.execute("DELETE FROM photo_albums WHERE kind != 'group' AND "
                "NOT EXISTS (SELECT 1 FROM photos ph WHERE ph.album_id = photo_albums.id)")


# ==================================================================== 儲存空間
_usage = {"at": 0.0, "bytes": 0}


def _bytes(path):
    """檔案或整個資料夾的大小。"""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def storage_paths():
    """算進用量的地方：上傳的檔案、資料庫。Azure 上整個 /home/data（含備份、舊站的資料庫）；
    本機資料庫放在專案資料夾，只算資料庫檔本身與備份。"""
    data = os.path.dirname(os.path.abspath(db.DB_PATH))
    if db.ON_AZURE:
        return [db.MEDIA_ROOT, data]
    return [db.MEDIA_ROOT, db.DB_PATH, os.path.join(data, "backups")]


def storage(refresh=False):
    """{used：資料庫＋上傳檔案用了多少, free：估計還剩多少, quota, low：該暫停收上傳了}。
    走一遍資料夾要花時間（Azure 的 /home 是網路磁碟），結果每個 worker 記 10 分鐘。"""
    now = time.time()
    if refresh or now - _usage["at"] > 600:
        _usage.update(at=now, bytes=sum(_bytes(p) for p in storage_paths() if os.path.exists(p)))
    os.makedirs(db.MEDIA_ROOT, exist_ok=True)
    free = shutil.disk_usage(db.MEDIA_ROOT).free
    if STORAGE_QUOTA:
        free = min(free, STORAGE_QUOTA - _usage["bytes"])
    return {"used": _usage["bytes"], "free": free, "quota": STORAGE_QUOTA, "low": free < STORAGE_RESERVE}


def keep_show_album(con, performance_id):
    """後台要刪掉一場演出（多半是重複建了同一場）：這場的演出相簿改成自訂相簿，照片都留著，
    名稱用原本的「日期 演出名稱」，建立的人之後可以在編輯頁把它連到正確的場次。
    要在 DELETE performances 之前呼叫（之後就查不到名稱了）；呼叫的人負責 commit。回傳新相簿的名稱，沒有相簿回傳 None。"""
    row = con.execute("SELECT a.id, p.event_date, p.event_name, p.event_name_en FROM photo_albums a "
                      "JOIN performances p ON p.id = a.performance_id WHERE a.kind = 'show' AND a.performance_id = ?",
                      (performance_id,)).fetchone()
    if not row:
        return None
    date = row["event_date"].replace("-", "/")
    title = ("%s %s" % (date, row["event_name"]))[:TITLE_MAX]
    title_en = ("%s %s" % (date, row["event_name_en"] or row["event_name"]))[:TITLE_MAX]
    con.execute("UPDATE photo_albums SET kind = 'custom', title = ?, title_en = ?, performance_id = NULL, updated_at = ? "
                "WHERE id = ?", (title, title_en, db.now(), row["id"]))
    return title


def cache_path(photo_id, size):
    return os.path.join(db.MEDIA_ROOT, "cache", "photos", "%d-%s.jpg" % (photo_id, size))


def remove_files(rows):
    """刪掉照片的原檔與縮圖。rows 要有 id、file。"""
    for r in rows:
        paths = [cache_path(r["id"], s) for s in SIZES]
        if r["file"]:
            paths.append(os.path.join(db.MEDIA_ROOT, r["file"]))
        for path in paths:
            if os.path.isfile(path):
                os.remove(path)


def past_shows(con, lang):
    """上傳時挑場次用（album.js 的篩選）：已經發生的演出，新到舊。"""
    return [{"id": r["id"], "d": r["event_date"], "n": i18n.tr(lang, r, "event_name"),
             "n2": r["event_name_en"] if lang == "zh" else r["event_name"],      # 搜尋時中英文名稱都比對
             "v": i18n.tr(lang, r, "venue"), "v2": r["venue_en"] if lang == "zh" else r["venue"],
             "c": r["city_id"], "cn": i18n.tr(lang, r, "city_name"), "t": r["event_type_id"]}
            for r in con.execute(Q.PERF_SELECT + " WHERE p.event_date <= ? ORDER BY p.event_date DESC, p.id DESC",
                                 (Q.today(),))]


def picker_context(con, lang):
    shows = past_shows(con, lang)
    used_cities = {s["c"] for s in shows}
    used_types = {s["t"] for s in shows}
    return {"shows": shows,
            "picker_types": [{"id": t["id"], "name": i18n.tr(lang, t, "name")} for t in Q.event_types(con) if t["id"] in used_types],
            "picker_cities": [{"id": c["id"], "name": i18n.tr(lang, c, "name")} for c in Q.cities(con) if c["id"] in used_cities]}


def performance(con, performance_id):
    return con.execute(Q.PERF_SELECT + " WHERE p.id = ?", (performance_id,)).fetchone() if performance_id else None


def show_label(lang, perf):
    return "%s %s" % (perf["event_date"].replace("-", "/"), i18n.tr(lang, perf, "event_name"))


PHOTO_SELECT = """
    SELECT ph.*, v.google_name, v.nickname, a.kind AS album_kind, a.title AS album_title, a.title_en AS album_title_en,
           a.performance_id AS album_performance_id, a.hidden AS album_hidden,
           p.event_date, p.event_name, p.event_name_en
    FROM photos ph JOIN photo_albums a ON a.id = ph.album_id
    LEFT JOIN visitors v ON v.id = ph.visitor_id
    LEFT JOIN performances p ON p.id = ph.performance_id
"""


def live(con):
    """公開的照片的條件：沒被下架；後台設定成要先審核的話，還要管理者看過（reviewed_at）。"""
    return "ph.status = 'live'" + (" AND ph.reviewed_at IS NOT NULL" if db.review_required(con, "photo") else "")


def visible_photos(con, visitor, where, args, order="ph.created_at, ph.id"):
    """公開的照片，加上自己被下架的（自己看得到，標出原因）。整本被下架的相簿不列。"""
    me = visitor["id"] if visitor else -1
    return con.execute(PHOTO_SELECT + " WHERE a.hidden = 0 AND (" + live(con) + " OR ph.visitor_id = ?) AND " + where +
                       " ORDER BY " + order, [me] + list(args)).fetchall()


def photo_items(lang, rows, visitor, review=False):
    """照片 → 模板與燈箱（album.js）用的資料。review＝後台設定成要先審核（還沒看過的標「等待審核」，只有上傳的人看得到）。"""
    anon = i18n.t(lang, "anonymous")
    out = []
    for r in rows:
        mine = bool(visitor and r["visitor_id"] == visitor["id"])
        item = {"id": r["id"], "media": r["media"], "caption": r["caption"], "date": r["created_at"][:10].replace("-", "/"),
                "by": V.display_name(r, r["name_mode"], anon) if r["google_name"] is not None else anon,
                "mine": mine, "removed": r["status"] == "removed", "note": r["admin_note"] if mine else "",
                "pending": review and r["status"] == "live" and not r["reviewed_at"],
                "w": r["width"], "h": r["height"]}
        if r["media"] == "image":
            item.update(thumb="/photos/img/%d/s.jpg" % r["id"], full="/photos/img/%d/l.jpg" % r["id"],
                        orig="/photos/img/%d/o.jpg" % r["id"])
        elif r["media"] == "video":
            item.update(video="/photos/video/%d" % r["id"])
        else:
            item.update(yt=r["youtube_id"], thumb="https://i.ytimg.com/vi/%s/hqdefault.jpg" % r["youtube_id"])
        if r["performance_id"]:
            item["show"] = {"id": r["performance_id"], "label": show_label(lang, r),
                            "url": i18n.link(lang, "/photos/show/%d/" % r["performance_id"])}
        if mine:
            item["edit"] = i18n.link(lang, "/photos/photo/%d/edit/" % r["id"])
            item["delete"] = "/photos/photo/%d/delete" % r["id"]
        out.append(item)
    return out


_ALBUM_SELECT = """
    SELECT a.*, p.event_date, p.event_name, p.event_name_en, v.google_name, v.nickname,
           (SELECT COUNT(*) FROM photos ph WHERE ph.album_id = a.id AND ph.status = 'live') AS n,
           (SELECT ph.id FROM photos ph WHERE ph.album_id = a.id AND ph.status = 'live' AND ph.media = 'image'
            ORDER BY ph.created_at DESC LIMIT 1) AS cover_id,
           (SELECT ph.youtube_id FROM photos ph WHERE ph.album_id = a.id AND ph.status = 'live' AND ph.media = 'youtube'
            ORDER BY ph.created_at DESC LIMIT 1) AS cover_yt
    FROM photo_albums a LEFT JOIN performances p ON p.id = a.performance_id LEFT JOIN visitors v ON v.id = a.visitor_id
"""


def album_select(con):
    """相簿＋公開的張數、封面（張數、封面只算公開的照片）。"""
    return _ALBUM_SELECT.replace("ph.status = 'live'", live(con))


def album_title(lang, a):
    if a["kind"] == "show":
        return i18n.tr(lang, a, "event_name") if a["event_name"] else i18n.t(lang, "album_show_gone")
    return i18n.tr(lang, a, "title")


def album_card(lang, a, visitor=None):
    cover = ("/photos/img/%d/s.jpg" % a["cover_id"] if a["cover_id"]
             else "https://i.ytimg.com/vi/%s/hqdefault.jpg" % a["cover_yt"] if a["cover_yt"] else "")
    return {"id": a["id"], "kind": a["kind"], "title": album_title(lang, a), "url": i18n.link(lang, album_url(a)),
            "n": a["n"], "cover": cover, "date": (a["event_date"] or "").replace("-", "/"), "year": (a["event_date"] or "")[:4],
            "show": show_label(lang, a) if a["kind"] == "custom" and a["event_date"] else "",
            "by": V.display_name(a, a["name_mode"], i18n.t(lang, "anonymous")) if a["google_name"] is not None else "",
            "mine": bool(visitor and a["visitor_id"] == visitor["id"])}


def show_photo_counts(con):
    """演出列表的 📷：每場有幾張公開的照片（含合照、影片）；只有自訂相簿整本連到這場、沒有單張標這場的記 0。"""
    counts = dict(con.execute(
        "SELECT ph.performance_id, COUNT(*) FROM photos ph JOIN photo_albums a ON a.id = ph.album_id "
        "WHERE " + live(con) + " AND a.hidden = 0 AND ph.performance_id IS NOT NULL GROUP BY ph.performance_id").fetchall())
    for (pid,) in con.execute("SELECT a.performance_id FROM photo_albums a WHERE a.kind = 'custom' AND a.hidden = 0 "
                              "AND a.performance_id IS NOT NULL AND EXISTS (SELECT 1 FROM photos ph "
                              "WHERE ph.album_id = a.id AND " + live(con) + ")"):
        counts.setdefault(pid, 0)
    return counts


# ==================================================================== 存檔
_heif_ready = False


def _open_heif():
    """讓 Pillow 讀得懂 iPhone 的 HEIC（pillow-heif）。讀進來時已經依拍攝方向轉正。"""
    global _heif_ready
    if not _heif_ready:
        import pillow_heif
        pillow_heif.register_heif_opener()
        _heif_ready = True


def store_image(upload):
    """照片：重新編碼成 JPEG（去掉 GPS、拍攝資訊），最長邊縮到 2400px。HEIC 也在這裡轉成 JPEG。回傳 (檔名, 寬, 高)。"""
    from PIL import Image, ImageOps
    _open_heif()
    raw = upload.file.read(PHOTO_MAX_BYTES + 1)
    if len(raw) > PHOTO_MAX_BYTES:
        raise ValueError("photo_too_large")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP", "GIF", "MPO", "HEIF"):
                raise ValueError("photo_bad_file")
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, "white")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.LANCZOS)
            name = "photos/%s.jpg" % secrets.token_hex(12)
            path = os.path.join(db.MEDIA_ROOT, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            im.save(path, format="JPEG", quality=86, optimize=True)
            return name, im.width, im.height
    except ValueError:
        raise
    except Exception:
        raise ValueError("photo_bad_file")


def video_ext(head):
    """看檔頭判斷影片格式（不信任副檔名）：MP4／MOV 第 4–8 個位元組是 ftyp，WebM 開頭是 EBML。"""
    if head[4:8] == b"ftyp":
        return ".mov" if head[8:10] == b"qt" else ".mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    return None


def store_video(upload):
    """影片原檔照存（伺服器不轉檔）。回傳 (檔名, None, None)。"""
    head = upload.file.read(16)
    ext = video_ext(head)
    if not ext:
        raise ValueError("video_bad_file")
    name = "photos/%s%s" % (secrets.token_hex(12), ext)
    path = os.path.join(db.MEDIA_ROOT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    size = len(head)
    with open(path, "wb") as out:
        out.write(head)
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > VIDEO_MAX_BYTES:
                out.close()
                os.remove(path)
                raise ValueError("video_too_large")
            out.write(chunk)
    return name, None, None


def store_all(uploads):
    """一次上傳的所有檔案存檔，回傳 [(media, 檔名, 寬, 高)]。有一個檔案不行就全部不收（已存的刪掉），丟出 ValueError。"""
    stored = []
    try:
        for u in uploads:
            stored.append(("video",) + store_video(u) if is_video(u) else ("image",) + store_image(u))
    except ValueError:
        for _, name, _, _ in stored:
            os.remove(os.path.join(db.MEDIA_ROOT, name))
        raise
    return stored


def is_video(upload):
    return (upload.content_type or "").startswith("video/") or \
        os.path.splitext(upload.filename or "")[1].lower() in VIDEO_TYPES


def show_album(con, performance_id, visitor_id, name_mode):
    """這場演出的演出相簿；還沒有就建立（建立的人＝第一個上傳的人）。"""
    row = con.execute("SELECT * FROM photo_albums WHERE kind = 'show' AND performance_id = ?", (performance_id,)).fetchone()
    if row:
        return row
    con.execute("INSERT INTO photo_albums (kind, performance_id, visitor_id, name_mode, created_at, updated_at) "
                "VALUES ('show', ?, ?, ?, ?, ?)", (performance_id, visitor_id, name_mode, db.now(), db.now()))
    return con.execute("SELECT * FROM photo_albums WHERE kind = 'show' AND performance_id = ?", (performance_id,)).fetchone()


def photos_today(con, visitor_id, media=None):
    """這個人 24 小時內傳了幾個（media＝只算影片之類）。"""
    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    return con.execute("SELECT COUNT(*) FROM photos WHERE visitor_id = ? AND created_at >= ?" + (" AND media = ?" if media else ""),
                       (visitor_id, since) + ((media,) if media else ())).fetchone()[0]


def youtube_lines(text):
    """合照的 YouTube 欄：一行一個網址 → 影片 ID 的清單（重複的只留一個）。認不出來的回傳 None。"""
    ids = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        yid = Q.youtube_id(line)
        if not yid:
            return None
        if yid not in ids:
            ids.append(yid)
    return ids


# ==================================================================== 前台頁面
def page_meta(title, title_en=None, summary=""):
    return {"title": title, "title_en": title_en or title, "summary": summary, "summary_en": ""}


@router.get("/photos/")
def album_index(request: Request, con=Depends(get_con)):
    lang, visitor = lang_of(request), current_visitor(request, con)
    ensure_group_album(con)
    group = con.execute(album_select(con) + " WHERE a.kind = 'group'").fetchone()
    recent_group = photo_items(lang, visible_photos(con, None, "a.kind = 'group' AND ph.media != 'video' AND " + live(con), (),
                                                    "ph.created_at DESC, ph.id DESC LIMIT 6"), None)
    me = visitor["id"] if visitor else -1
    shows = [album_card(lang, a, visitor) for a in con.execute(
        album_select(con) + " WHERE a.kind = 'show' AND a.hidden = 0 ORDER BY p.event_date DESC, a.id DESC") if a["n"]]
    custom = [album_card(lang, a, visitor) for a in con.execute(
        album_select(con) + " WHERE a.kind = 'custom' AND a.hidden = 0 ORDER BY a.updated_at DESC, a.id DESC")
        if a["n"] or a["visitor_id"] == me]
    return render(request, con, "album_index.html", {
        "group": album_card(lang, group), "recent_group": recent_group, "show_albums": shows, "custom_albums": custom,
        "msg": request.query_params.get("msg"), "contact_email": db.get_setting(con, "contact_email"),
    }, page=album_page(con) or page_meta("相簿", "Photos", "粉絲分享的 163braces 演出現場照片、合照與影片。"))


def view(request, con, ctx, title, title_en=None, summary=""):
    return render(request, con, "album_view.html", dict(ctx, msg=request.query_params.get("msg")),
                  page=page_meta(title, title_en, summary))


@router.get("/photos/show/{performance_id:int}/")
def show_photos(performance_id: int, request: Request, con=Depends(get_con)):
    """一場演出的所有照片。"""
    lang, visitor = lang_of(request), current_visitor(request, con)
    perf = performance(con, performance_id) or _404()
    album = con.execute("SELECT * FROM photo_albums WHERE kind = 'show' AND performance_id = ?", (performance_id,)).fetchone()
    review = db.review_required(con, "photo")
    own = photo_items(lang, visible_photos(con, visitor, "a.kind = 'show' AND a.performance_id = ?", (performance_id,)), visitor, review)
    group = photo_items(lang, visible_photos(con, visitor, "a.kind = 'group' AND ph.performance_id = ?", (performance_id,)), visitor, review)
    others = photo_items(lang, visible_photos(con, visitor, "a.kind = 'custom' AND ph.performance_id = ?", (performance_id,)), visitor, review)
    linked = [album_card(lang, a, visitor) for a in con.execute(
        album_select(con) + " WHERE a.kind = 'custom' AND a.hidden = 0 AND a.performance_id = ? ORDER BY a.updated_at DESC",
        (performance_id,)) if a["n"]]
    sections = [s for s in [
        {"key": "own", "title": i18n.t(lang, "album_this_show"), "items": own},
        {"key": "group", "title": i18n.t(lang, "album_group"), "items": group,
         "more": i18n.link(lang, "/photos/group/")},
        {"key": "others", "title": i18n.t(lang, "album_from_others"), "items": others},
    ] if s["items"]]
    upload = i18n.link(lang, "/photos/upload/?to=show&show=%d" % performance_id)
    title = i18n.tr(lang, perf, "event_name")
    return view(request, con, {
        "kind": "show", "perf": perf, "sections": sections, "linked_albums": linked, "upload_url": upload,
        "group_upload_url": i18n.link(lang, "/photos/upload/?to=group&show=%d" % performance_id),
        "heading": title, "album": album,
    }, "%s · %s" % (perf["event_name"], "相簿"), "%s · Photos" % (perf["event_name_en"] or perf["event_name"]))


@router.get("/photos/group/")
def group_photos(request: Request, con=Depends(get_con)):
    """合照：依場次分段，新的場次在上面。"""
    lang, visitor = lang_of(request), current_visitor(request, con)
    album = group_album(con)
    rows = visible_photos(con, visitor, "a.kind = 'group'", (), "p.event_date DESC, ph.performance_id, ph.created_at, ph.id")
    sections = []
    for item, r in zip(photo_items(lang, rows, visitor, db.review_required(con, "photo")), rows):
        key = r["performance_id"] or 0
        if not sections or sections[-1]["pid"] != key:
            sections.append({"pid": key, "key": "g%d" % key,
                             "title": show_label(lang, r) if key else i18n.t(lang, "album_no_show"),
                             "more": i18n.link(lang, "/photos/show/%d/" % key) if key else "", "items": []})
        sections[-1]["items"].append(item)
    return view(request, con, {
        "kind": "group", "album": album, "sections": sections, "heading": i18n.tr(lang, album, "title"),
        "upload_url": i18n.link(lang, "/photos/upload/?to=group"),
    }, "合照 · 相簿", "Group photos · Photos", "粉絲跟 163braces 的合照與影片，依演出場次整理。")


@router.get("/photos/{album_id:int}/")
def custom_album(album_id: int, request: Request, con=Depends(get_con)):
    lang, visitor = lang_of(request), current_visitor(request, con)
    album = con.execute(album_select(con) + " WHERE a.id = ?", (album_id,)).fetchone() or _404()
    if album["kind"] != "custom" and album_url(album) != "/photos/%d/" % album_id:     # 演出相簿、合照有自己的網址
        return RedirectResponse(prefix(request) + album_url(album), status_code=301)
    if album["hidden"] and not is_admin(request, con):
        _404()
    card = album_card(lang, album, visitor)
    items = photo_items(lang, visible_photos(con, visitor, "ph.album_id = ?", (album_id,)), visitor, db.review_required(con, "photo"))
    return view(request, con, {
        "kind": "custom", "album": album, "card": card, "heading": card["title"],
        "sections": [{"key": "all", "title": "", "items": items}] if items else [],
        "perf": performance(con, album["performance_id"]),
        "upload_url": i18n.link(lang, "/photos/upload/?to=custom&album=%d" % album_id),
        "edit_url": i18n.link(lang, "/photos/%d/edit/" % album_id) if card["mine"] else "",
    }, "%s · 相簿" % album["title"], "%s · Photos" % album["title"], album["description"][:150])


# ==================================================================== 圖檔
def _public(con, row):
    return (row["status"] == "live" and not row["hidden"] and (row["reviewed_at"] or not db.review_required(con, "photo"))
            and db.album_published(con))


def _viewable(request, con, row):
    """公開的照片誰都看得到；下架、等待審核、整本被下架的只給上傳的人與管理者。"""
    if _public(con, row):
        return True
    visitor = current_visitor(request, con)
    return bool(visitor and visitor["id"] == row["visitor_id"]) or bool(auth.current_user(con, request.cookies.get(auth.COOKIE)))


def _media_row(con, photo_id, media):
    return con.execute("SELECT ph.id, ph.file, ph.status, ph.reviewed_at, ph.visitor_id, a.hidden FROM photos ph "
                       "JOIN photo_albums a ON a.id = ph.album_id WHERE ph.id = ? AND ph.media = ?",
                       (photo_id, media)).fetchone()


@router.get("/photos/img/{photo_id:int}/{size}.jpg")
def photo_image(photo_id: int, size: str, request: Request, con=Depends(get_con)):
    """照片：s 格子用的縮圖、l 點開看的大圖、o 原檔（2400px）。下架的只給上傳的人與管理者看，不讓瀏覽器快取。"""
    if size not in SIZES and size != "o":
        _404()
    row = _media_row(con, photo_id, "image") or _404()
    if not _viewable(request, con, row):
        _404()
    src = os.path.join(db.MEDIA_ROOT, row["file"])
    if not os.path.isfile(src):
        _404()
    cache = {"Cache-Control": "public, max-age=2592000"} if _public(con, row) else {"Cache-Control": "private, no-store"}
    if size == "o":
        return FileResponse(src, media_type="image/jpeg", headers=cache)
    out = cache_path(photo_id, size)
    if not os.path.isfile(out):
        from PIL import Image
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail((SIZES[size], SIZES[size]), Image.LANCZOS)
            im.convert("RGB").save(out + ".tmp", format="JPEG", quality=82, optimize=True)
        os.replace(out + ".tmp", out)
    return FileResponse(out, media_type="image/jpeg", headers=cache)


@router.get("/photos/video/{photo_id:int}")
def photo_video(photo_id: int, request: Request, con=Depends(get_con)):
    """影片檔：FileResponse 支援 Range，瀏覽器可以邊下載邊播、拖進度條。"""
    row = _media_row(con, photo_id, "video") or _404()
    if not _viewable(request, con, row):
        _404()
    path = os.path.join(db.MEDIA_ROOT, row["file"])
    if not os.path.isfile(path):
        _404()
    return FileResponse(path, media_type=VIDEO_TYPES.get(os.path.splitext(path)[1], "video/mp4"),
                        headers={"Cache-Control": "public, max-age=604800" if _public(con, row) else "private, no-store"})


# ==================================================================== 上傳
def custom_choices(con, lang):
    """自訂相簿的下拉選單：所有沒被下架的自訂相簿（任何人都可以傳到別人建的相簿），最近有更新的在前面。"""
    return [{"id": a["id"], "title": a["title"], "show": show_label(lang, a) if a["event_date"] else ""}
            for a in con.execute(album_select(con) + " WHERE a.kind = 'custom' AND a.hidden = 0 ORDER BY a.updated_at DESC")]


@router.get("/photos/upload/")
def upload_form(request: Request, con=Depends(get_con)):
    lang, visitor = lang_of(request), current_visitor(request, con)
    qp = request.query_params
    to = qp.get("to") if qp.get("to") in ("show", "custom", "group") else "show"
    return render(request, con, "album_upload.html", dict(picker_context(con, lang), **{
        "to": to, "show_id": as_id(qp.get("show")), "album_id": as_id(qp.get("album")),
        "albums": custom_choices(con, lang), "error": qp.get("error"),
        "need_login": not visitor or V.is_guest(visitor),
        "blocked": submit_block(request, visitor) if visitor and not V.is_guest(visitor) else None,
        "closed": closed(request, con, "photo") or (T(request, "album_storage_full") if storage()["low"] else None),
        "max_items": MAX_ITEMS, "video_mb": VIDEO_MAX_BYTES // 1024 // 1024, "photo_mb": PHOTO_MAX_BYTES // 1024 // 1024,
        "total_mb": UPLOAD_MAX_BYTES // 1024 // 1024, "video_daily": VIDEO_DAILY,
        "contact_email": db.get_setting(con, "contact_email"),
    }), page=page_meta("上傳照片", "Upload photos"))


@router.post("/photos/upload/")
async def upload(request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request, prefix(request) + "/photos/upload/"), status_code=303)
    # 總大小超過就不收：先看 Content-Length（還沒開始讀檔案就擋掉；多留 1MB 給表單欄位與分隔線）
    total_mb = UPLOAD_MAX_BYTES // 1024 // 1024
    too_big = prefix(request) + "/photos/upload/?error=" + quote(T(request, "album_total_too_large", mb=total_mb))
    length = as_id(request.headers.get("content-length")) or 0
    if length > UPLOAD_MAX_BYTES + 1024 * 1024:
        return RedirectResponse(too_big, status_code=303)
    # 空間不夠（或收了這批就不夠）：一樣還沒讀檔案就擋掉
    space = await run_in_threadpool(storage)
    if space["low"] or space["free"] - length < STORAGE_RESERVE:
        return RedirectResponse(prefix(request) + "/photos/upload/?error=" + quote(T(request, "album_storage_full")), status_code=303)
    form = await request.form()
    target = form.get("target") if form.get("target") in ("show", "custom", "group") else "show"
    pid = as_id(form.get("performance_id"))
    album_choice = (form.get("album_id") or "").strip()
    back = prefix(request) + "/photos/upload/?to=%s%s%s" % (
        target, "&show=%d" % pid if pid else "", "&album=" + quote(album_choice) if album_choice.isdigit() else "")

    def fail(key, **kw):
        return RedirectResponse(back + "&error=" + quote(T(request, key, **kw)), status_code=303)
    blocked = submit_block(request, visitor) or closed(request, con, "photo")
    if blocked:
        return RedirectResponse(back + "&error=" + quote(blocked), status_code=303)
    perf = performance(con, pid)
    if pid and not perf:
        return fail("album_need_show")
    if target in ("show", "group") and not perf:
        return fail("album_need_show")
    uploads = [u for u in form.getlist("files") if getattr(u, "filename", "")]
    if sum(u.size or 0 for u in uploads) > UPLOAD_MAX_BYTES:       # 沒有 Content-Length 的（分段傳送）在這裡擋
        return RedirectResponse(too_big, status_code=303)
    videos = [u for u in uploads if is_video(u)]
    yt = youtube_lines(form.get("youtube")) if target == "group" else []
    if yt is None:
        return fail("album_bad_youtube")
    if videos and target != "group":
        return fail("album_video_group_only")
    total = len(uploads) + len(yt)
    if not total:
        return fail("album_need_files")
    if total > MAX_ITEMS:
        return fail("album_too_many", n=MAX_ITEMS)
    if not form.get("own_ok"):
        return fail("album_need_own")
    if photos_today(con, visitor["id"]) + total > V.DAILY_LIMITS["photo"]:
        return fail("daily_limit", n=V.DAILY_LIMITS["photo"])
    if videos and photos_today(con, visitor["id"], "video") + len(videos) > VIDEO_DAILY:
        return fail("album_video_daily", n=VIDEO_DAILY)
    mode = form.get("name_mode") if form.get("name_mode") in V.NAME_MODES else "nickname"
    album = None
    if target == "custom":
        if album_choice == "new":
            title = " ".join((form.get("new_title") or "").split())[:TITLE_MAX]
            if not title:
                return fail("album_need_title")
            if V.over_daily_limit(con, "album", visitor["id"]):
                return fail("daily_limit", n=V.DAILY_LIMITS["album"])
        else:
            album = con.execute("SELECT * FROM photo_albums WHERE id = ? AND kind = 'custom' AND hidden = 0",
                                (as_id(album_choice),)).fetchone()
            if not album:
                return fail("album_need_album")
    try:
        # 壓縮照片、寫影片檔要好幾秒；丟到背景執行緒做，這個 worker 才能繼續回應其他訪客
        stored = await run_in_threadpool(store_all, uploads)
    except ValueError as e:
        return fail(str(e), mb=VIDEO_MAX_BYTES // 1024 // 1024)
    _usage["bytes"] += sum(os.path.getsize(os.path.join(db.MEDIA_ROOT, name)) for _, name, _, _ in stored)   # 下次重算前先自己加上
    now = db.now()
    if target == "group":
        album = group_album(con)
    elif target == "show":
        album = show_album(con, pid, visitor["id"], mode)
    elif album is None:
        album_id = con.execute(
            "INSERT INTO photo_albums (kind, title, description, performance_id, visitor_id, name_mode, created_at, updated_at) "
            "VALUES ('custom', ?, ?, ?, ?, ?, ?, ?)",
            (" ".join((form.get("new_title") or "").split())[:TITLE_MAX], (form.get("new_description") or "").strip()[:500],
             pid if perf and form.get("album_link") else None, visitor["id"], mode, now, now)).lastrowid
        album = con.execute("SELECT * FROM photo_albums WHERE id = ?", (album_id,)).fetchone()
    caption = " ".join((form.get("caption") or "").split())[:CAPTION_MAX]
    rows = [(album["id"], visitor["id"], pid if perf else None, media, name, "", w, h, caption, mode, now)
            for media, name, w, h in stored]
    rows += [(album["id"], visitor["id"], pid, "youtube", "", yid, None, None, caption, mode, now) for yid in yt]
    con.executemany("INSERT INTO photos (album_id, visitor_id, performance_id, media, file, youtube_id, width, height, "
                    "caption, name_mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("UPDATE photo_albums SET updated_at = ? WHERE id = ?", (now, album["id"]))
    con.commit()
    pagecache.invalidate()                              # 演出列表上的 📷 跟著更新
    return RedirectResponse(prefix(request) + album_url(album) + "?msg=" + quote(T(request, "album_uploaded_review" if db.review_required(con, "photo") else "album_uploaded", n=total)),
                            status_code=303)


# ==================================================================== 自己的照片、相簿：修改、刪除
def own_photo(con, visitor, photo_id):
    if not visitor:
        return None
    return con.execute(PHOTO_SELECT + " WHERE ph.id = ? AND ph.visitor_id = ?", (photo_id, visitor["id"])).fetchone()


@router.get("/photos/photo/{photo_id:int}/edit/")
def photo_edit_form(photo_id: int, request: Request, con=Depends(get_con)):
    lang, visitor = lang_of(request), current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    row = own_photo(con, visitor, photo_id) or _404()
    album = con.execute("SELECT * FROM photo_albums WHERE id = ?", (row["album_id"],)).fetchone()
    return render(request, con, "album_photo_edit.html", dict(picker_context(con, lang), **{
        "photo": photo_items(lang, [row], visitor, db.review_required(con, "photo"))[0], "row": row, "album_kind": album["kind"],
        "back": i18n.link(lang, album_url(album)), "error": request.query_params.get("error"),
    }), page=page_meta("編輯照片", "Edit photo"))


@router.post("/photos/photo/{photo_id:int}/edit/")
async def photo_edit(photo_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    row = own_photo(con, visitor, photo_id) or _404()
    form = await request.form()
    pid = as_id(form.get("performance_id"))
    if pid and not performance(con, pid):
        pid = None
    if row["album_kind"] == "show":
        pid = row["performance_id"]                     # 演出相簿的照片跟著相簿的場次
    elif row["album_kind"] == "group" and not pid:
        return RedirectResponse(request.url.path + "?error=" + quote(T(request, "album_need_show")), status_code=303)
    mode = form.get("name_mode") if form.get("name_mode") in V.NAME_MODES else row["name_mode"]
    con.execute("UPDATE photos SET caption = ?, performance_id = ?, name_mode = ? WHERE id = ?",
                (" ".join((form.get("caption") or "").split())[:CAPTION_MAX], pid, mode, photo_id))
    con.commit()
    pagecache.invalidate()
    album = con.execute("SELECT * FROM photo_albums WHERE id = ?", (row["album_id"],)).fetchone()
    return RedirectResponse(prefix(request) + album_url(album) + "?msg=" + quote(T(request, "saved")) + "#p%d" % photo_id,
                            status_code=303)


@router.post("/photos/photo/{photo_id:int}/delete")
def photo_delete(photo_id: int, request: Request, con=Depends(get_con)):
    """刪除自己的照片（下架的也可以刪）。相簿刪到空了就整本刪掉。"""
    check_post(request)
    visitor = current_visitor(request, con)
    row = own_photo(con, visitor, photo_id) or _404()
    album = con.execute("SELECT * FROM photo_albums WHERE id = ?", (row["album_id"],)).fetchone()
    con.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    drop_empty_albums(con)
    con.commit()
    remove_files([row])
    pagecache.invalidate()
    still = con.execute("SELECT 1 FROM photo_albums WHERE id = ?", (album["id"],)).fetchone()
    target = album_url(album) if still or album["kind"] == "show" else "/photos/"
    if not db.album_published(con):                     # 相簿關閉中：是從「我的投稿」刪的，回那裡
        target = "/me/?tab=submissions"
        return RedirectResponse(prefix(request) + target + "&msg=" + quote(T(request, "album_photo_deleted")), status_code=303)
    return RedirectResponse(prefix(request) + target + "?msg=" + quote(T(request, "album_photo_deleted")), status_code=303)


def own_album(con, visitor, album_id):
    if not visitor:
        return None
    return con.execute("SELECT * FROM photo_albums WHERE id = ? AND kind = 'custom' AND visitor_id = ?",
                       (album_id, visitor["id"])).fetchone()


@router.get("/photos/{album_id:int}/edit/")
def album_edit_form(album_id: int, request: Request, con=Depends(get_con)):
    lang, visitor = lang_of(request), current_visitor(request, con)
    if not visitor:
        return RedirectResponse(login_url(request), status_code=303)
    album = own_album(con, visitor, album_id) or _404()
    others = con.execute("SELECT COUNT(*) FROM photos WHERE album_id = ? AND visitor_id IS NOT ?",
                         (album_id, visitor["id"])).fetchone()[0]
    return render(request, con, "album_edit.html", dict(picker_context(con, lang), **{
        "album": album, "others": others, "back": i18n.link(lang, album_url(album)),
        "error": request.query_params.get("error"),
    }), page=page_meta("編輯相簿", "Edit album"))


@router.post("/photos/{album_id:int}/edit/")
async def album_edit(album_id: int, request: Request, con=Depends(get_con)):
    check_post(request)
    visitor = current_visitor(request, con)
    album = own_album(con, visitor, album_id) or _404()
    form = await request.form()
    if form.get("action") == "delete":
        # 只有自己的照片時才能整本刪（別人傳的照片只有他們自己能刪）
        if con.execute("SELECT 1 FROM photos WHERE album_id = ? AND visitor_id IS NOT ?", (album_id, visitor["id"])).fetchone():
            return RedirectResponse(request.url.path + "?error=" + quote(T(request, "album_has_others")), status_code=303)
        rows = con.execute("SELECT id, file FROM photos WHERE album_id = ?", (album_id,)).fetchall()
        con.execute("DELETE FROM photo_albums WHERE id = ?", (album_id,))
        con.commit()
        remove_files(rows)
        pagecache.invalidate()
        return RedirectResponse(prefix(request) + "/photos/?msg=" + quote(T(request, "album_deleted")), status_code=303)
    title = " ".join((form.get("title") or "").split())[:TITLE_MAX]
    if not title:
        return RedirectResponse(request.url.path + "?error=" + quote(T(request, "album_need_title")), status_code=303)
    pid = as_id(form.get("performance_id"))
    if pid and not performance(con, pid):
        pid = None
    mode = form.get("name_mode") if form.get("name_mode") in V.NAME_MODES else album["name_mode"]
    con.execute("UPDATE photo_albums SET title = ?, description = ?, performance_id = ?, name_mode = ? WHERE id = ?",
                (title, (form.get("description") or "").strip()[:500], pid, mode, album_id))
    con.commit()
    pagecache.invalidate()
    return RedirectResponse(prefix(request) + album_url(album) + "?msg=" + quote(T(request, "saved")), status_code=303)


def my_photo_albums(con, lang, visitor_id):
    """「我的投稿」：我上傳過照片的相簿，各有幾張、幾張被下架。"""
    rows = con.execute(
        "SELECT a.*, p.event_date, p.event_name, p.event_name_en, NULL AS google_name, NULL AS nickname, "
        "COUNT(ph.id) AS mine, SUM(ph.status = 'removed') AS removed, MAX(ph.created_at) AS last "
        "FROM photos ph JOIN photo_albums a ON a.id = ph.album_id LEFT JOIN performances p ON p.id = a.performance_id "
        "WHERE ph.visitor_id = ? GROUP BY a.id ORDER BY last DESC", (visitor_id,)).fetchall()
    return [{"title": album_title(lang, a), "url": i18n.link(lang, album_url(a)), "mine": a["mine"],
             "removed": a["removed"] or 0, "hidden": a["hidden"]} for a in rows]


def my_photos(con, lang, visitor):
    """相簿關閉時「我的投稿」列出自己上傳的每一張（縮圖、在哪本相簿、刪除）。"""
    rows = con.execute(PHOTO_SELECT + " WHERE ph.visitor_id = ? ORDER BY ph.created_at DESC, ph.id DESC", (visitor["id"],)).fetchall()
    return [dict(item, album=album_title(lang, dict(r, kind=r["album_kind"], title=r["album_title"], title_en=r["album_title_en"],
                                                  event_name=r["event_name"] if r["album_kind"] == "show" else None)))
            for item, r in zip(photo_items(lang, rows, visitor), rows)]


def sitemap_urls(con):
    """相簿首頁 /photos/ 是 pages 表裡的頁面，sitemap 已經列了；這裡列底下的。相簿頁沒上線就都不列。"""
    if not db.album_published(con):
        return []
    urls = ["/photos/group/"]
    urls += ["/photos/show/%d/" % r[0] for r in con.execute(
        "SELECT DISTINCT ph.performance_id FROM photos ph JOIN photo_albums a ON a.id = ph.album_id "
        "WHERE " + live(con) + " AND a.hidden = 0 AND ph.performance_id IS NOT NULL")]
    urls += ["/photos/%d/" % r[0] for r in con.execute(
        "SELECT a.id FROM photo_albums a WHERE a.kind = 'custom' AND a.hidden = 0 AND EXISTS "
        "(SELECT 1 FROM photos ph WHERE ph.album_id = a.id AND " + live(con) + ")")]
    return urls
