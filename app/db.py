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
    "home_top_songs_count": "5",        # 首頁「最近常唱」顯示幾首
    "home_top_songs_window": "20",      # 「最近常唱」看最近幾場有歌單的演出
    "setlist_top_songs_count": "10",    # 歌單分頁的累積圖表預設顯示幾首
    "show_donation_call": "0",
    "donation_amount": "10",
    "replay_logo_id": "",
    "charts_intro_html": "",
    "charts_intro_html_en": "",
    "setlist_intro_html": "",
    "replay_intro_html": "",
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


def get_setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else SETTINGS.get(key, "")


def set_setting(con, key, value):
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
