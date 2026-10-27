-- 163braces 資訊站的資料庫（site.sqlite3）。
--
-- 雙語一律「同一列並存」：每個要翻譯的欄位都有 _en 版本，英文留空時前台退回中文。
-- 排序欄位一律叫 sort_order，數字越小越前面。
--
--   演出資料   event_types、cities、performances、setlist_items
--   曲庫       albums、songs、lyrics
--   頁面       pages（首頁、演出、歌詞索引這些固定頁面也在這裡，才能在後台改標題、縮圖、網址）
--   其他       images、settings、redirects、users、sessions

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS images (
    id          INTEGER PRIMARY KEY,
    file        TEXT NOT NULL,          -- 相對 MEDIA_ROOT 的路徑，例：original_images/xxx.jpg
    title       TEXT NOT NULL DEFAULT '',
    width       INTEGER,
    height      INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_types (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    name_en     TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cities (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    name_en     TEXT NOT NULL DEFAULT '',
    map_key     TEXT NOT NULL DEFAULT '',   -- 對應地圖上的縣市（app/taiwan.py）；空白＝不畫在地圖上，例如「海外」
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS performances (
    id                       INTEGER PRIMARY KEY,
    event_date               TEXT NOT NULL,     -- YYYY-MM-DD
    event_name               TEXT NOT NULL,
    event_name_en            TEXT NOT NULL DEFAULT '',
    event_type_id            INTEGER NOT NULL REFERENCES event_types(id),
    venue                    TEXT NOT NULL DEFAULT '',
    venue_en                 TEXT NOT NULL DEFAULT '',
    city_id                  INTEGER NOT NULL REFERENCES cities(id),
    setlist_order_uncertain  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS performances_date ON performances(event_date);

-- 歌單的一行：從曲庫選歌（song_id），或填自訂曲名（翻唱、曲庫沒有的歌），兩者擇一。
CREATE TABLE IF NOT EXISTS setlist_items (
    id              INTEGER PRIMARY KEY,
    performance_id  INTEGER NOT NULL REFERENCES performances(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    song_id         INTEGER REFERENCES songs(id),
    custom_title    TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    CHECK ((song_id IS NULL) != (custom_title = ''))
);
CREATE INDEX IF NOT EXISTS setlist_items_performance ON setlist_items(performance_id, position);
CREATE INDEX IF NOT EXISTS setlist_items_song ON setlist_items(song_id);

CREATE TABLE IF NOT EXISTS albums (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    name_en         TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    description_en  TEXT NOT NULL DEFAULT '',
    release_date    TEXT NOT NULL DEFAULT '',
    cover_image_id  INTEGER REFERENCES images(id) ON DELETE SET NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS songs (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    title_en        TEXT NOT NULL DEFAULT '',
    artist          TEXT NOT NULL DEFAULT '',   -- 留空＝163braces 自己的歌；翻唱才填
    artist_en       TEXT NOT NULL DEFAULT '',
    album_id        INTEGER NOT NULL REFERENCES albums(id),
    cover_image_id  INTEGER REFERENCES images(id) ON DELETE SET NULL,  -- 單曲封面；空白就用專輯封面
    listen_url      TEXT NOT NULL DEFAULT '',   -- 首頁「隨機聆聽」播的影片（YouTube）
    -- 這首歌用哪一份歌詞。改編版、日文版可以跟原曲指向同一份，歌名維持各自的寫法。
    lyrics_id       INTEGER REFERENCES lyrics(id) ON DELETE SET NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS songs_lyrics ON songs(lyrics_id);

-- 歌詞。sections_json 是一串區塊，依序排列：
--   {"type": "section", "name": "Verse 1", "name_alt": "主歌", "lines": [{"left": "…", "right": "…"}, …]}
--   {"type": "note", "html": "<p>說明文字</p>"}
--   {"type": "part", "title": "補充", "title_en": "Supplement"}
--       分隔：之後的區塊放進另一個有標題的方框（舊版本、創作理念這類非主要歌詞）
-- display_mode：bilingual 中英對照、duet 對唱（左右兩個聲部）、single 單欄。
-- videos_json：[{"title": "…", "title_en": "…", "url": "https://youtu.be/…"}, …]
-- review_json：需要人確認的地方（例如轉檔時中英文版歌詞不一致），後台會提醒；確認後清空。
--   [{"message": "…"}, …]
-- 哪些歌曲用這份歌詞記在 songs.lyrics_id。
CREATE TABLE IF NOT EXISTS lyrics (
    id              INTEGER PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    title_en        TEXT NOT NULL DEFAULT '',
    artist          TEXT NOT NULL DEFAULT '',
    composer        TEXT NOT NULL DEFAULT '',
    lyricist        TEXT NOT NULL DEFAULT '',
    release_year    INTEGER,
    display_mode    TEXT NOT NULL DEFAULT 'bilingual' CHECK (display_mode IN ('bilingual', 'duet', 'single')),
    left_label      TEXT NOT NULL DEFAULT '中文',
    right_label     TEXT NOT NULL DEFAULT 'English',
    intro_html      TEXT NOT NULL DEFAULT '',
    intro_html_en   TEXT NOT NULL DEFAULT '',
    sections_json   TEXT NOT NULL DEFAULT '[]',
    videos_json     TEXT NOT NULL DEFAULT '[]',
    review_json     TEXT NOT NULL DEFAULT '[]',
    published       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

-- 網站上的每一頁。kind 決定用哪個版型：
--   home 首頁、performances 演出（列表、統計、歌單、年度回顧四個分頁）、lyrics 歌詞索引、
--   articles 文章列表、article 文章、page 一般內容頁
-- 固定頁面（home、performances、lyrics、articles）各只有一頁，可以改網址但不能刪。
-- slug 是完整路徑、不含前後斜線，例：articles/fanpages；首頁是空字串。
-- 歌詞頁的網址＝歌詞索引頁的 slug＋歌詞的 slug；文章同理。
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('home', 'performances', 'lyrics', 'articles', 'article', 'page')),
    slug            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    title_en        TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',   -- 列表、搜尋引擎、社群分享用的一句話
    summary_en      TEXT NOT NULL DEFAULT '',
    thumbnail_id    INTEGER REFERENCES images(id) ON DELETE SET NULL,
    body_html       TEXT NOT NULL DEFAULT '',
    body_html_en    TEXT NOT NULL DEFAULT '',
    published       INTEGER NOT NULL DEFAULT 1,
    published_at    TEXT,                       -- 文章的發佈日期
    sort_order      INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

-- 全站設定，值一律存字串。key 與預設值見 app/db.py 的 SETTINGS。
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- 舊網址 → 新網址（301）。改頁面網址時自動新增一筆。
CREATE TABLE IF NOT EXISTS redirects (
    old_path  TEXT PRIMARY KEY,   -- 開頭有斜線、結尾有斜線，例：/replay/
    new_path  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,      -- 雜湊，格式見 app/auth.py
    is_active   INTEGER NOT NULL DEFAULT 1,
    last_login  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,   -- cookie 憑證的 SHA-256，資料庫不存原值
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
