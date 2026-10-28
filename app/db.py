"""資料庫連線與路徑。

Azure App Service 上只有 /home 會保留（重新部署、重啟都不會清掉），所以資料庫和上傳的圖片
都放在 /home 底下；靠 WEBSITE_SITE_NAME（Azure 自動設定的環境變數）判斷是不是在 Azure 上。

不開 WAL：Azure 的 /home 是網路磁碟，SQLite 官方文件說 WAL 不能用在網路檔案系統上。
"""
import datetime
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ON_AZURE = bool(os.environ.get("WEBSITE_SITE_NAME"))

DB_PATH = os.environ.get("DB_PATH") or (
    "/home/data/site.sqlite3" if ON_AZURE else os.path.join(BASE_DIR, "site.sqlite3")
)
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or (
    "/home/media" if ON_AZURE else os.path.join(BASE_DIR, "media")
)
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# 全站設定的預設值。資料庫沒有這個 key 時用這裡的值。
SETTINGS = {
    "site_name": "163braces 資訊站",
    "site_name_en": "163braces Info",
    "contact_email": "163braces.translate@gmail.com",
    "site_logo_id": "",                 # 頁首左上角與瀏覽器分頁圖示；空白就用內建的「163」圖示
    "home_hero_image_id": "",           # 首頁大標題方框的背景圖
    "home_hero_mode": "cover",          # cover 滿版背景／side 放在右半邊往左淡出
    "home_hero_overlay": "70",          # 白色遮罩濃度 0–100，越高圖越淡、字越清楚
    "home_hero_pos_x": "50",            # 背景圖對齊位置（0–100%），在後台「首頁大標題」用拖的設定
    "home_hero_pos_y": "50",
    "home_hero_zoom": "100",            # 背景圖放大比例（100–300%）
    "home_upcoming_count": "5",         # 首頁「即將演出」顯示幾場
    "home_recent_count": "3",           # 沒有即將演出時，改列幾場「最近的演出」；0＝不列
    "home_top_songs_count": "5",        # 首頁「最近常唱」顯示幾首
    "home_top_songs_window": "20",      # 「最近常唱」看最近幾場有歌單的演出
    "setlist_top_songs_count": "10",    # 歌單分頁的累積圖表預設顯示幾首
    "setlist_prob_window": "10",        # 歌單分頁「演出機率對照表」左邊預設看最近幾場
    "show_donation_call": "0",
    "donation_amount": "10",
    "replay_logo_id": "",
    "charts_intro_html": "",
    "charts_intro_html_en": "",
    "setlist_intro_html": "",
    "replay_intro_html": "",
    "tab_status_charts": "live",        # 演出頁三個分頁各自的狀態（live／unpublished／draft），在後台分頁的編輯畫面改
    "tab_status_setlist": "live",
    "tab_status_replay": "live",
    "home_facts_json": "[]",
    "lyrics_other_position": "",        # 歌詞索引「其他歌詞」排在第幾張專輯後面；空白＝最後
}


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def connect(path=None, readonly=False):
    path = path or DB_PATH
    if readonly:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30, check_same_thread=False)
    else:
        # FastAPI 的相依注入與路由函式可能跑在不同執行緒，連線本身仍只給一個請求用
        con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def init(con):
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    # 舊版資料庫補欄位（CREATE TABLE IF NOT EXISTS 不會幫已經存在的表加欄位）
    from . import pagetree
    pagetree.ensure_schema(con)
    for table in ("pages", "lyrics"):
        if "status" not in [r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)]:
            con.execute("ALTER TABLE %s ADD COLUMN status TEXT NOT NULL DEFAULT 'live' "
                        "CHECK (status IN ('live', 'unpublished', 'draft'))" % table)
            # 舊資料只知道有沒有發佈：沒發佈的當成草稿
            con.execute("UPDATE %s SET status = 'draft' WHERE published = 0" % table)
            con.commit()


STATUSES = {"live": "線上", "unpublished": "取消發佈", "draft": "草稿"}


def status_after(action, current, is_new):
    """後台按鈕 → 新狀態。「儲存」不改狀態（新頁面存成草稿）；「發佈」上線；「取消發佈」只對線上的頁面有效。"""
    if action == "publish":
        return "live"
    if action == "unpublish":
        return "unpublished" if current == "live" else current
    return "draft" if is_new else current


def get_setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else SETTINGS.get(key, "")


def set_setting(con, key, value):
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
