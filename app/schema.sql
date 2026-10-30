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
    setlist_order_uncertain  INTEGER NOT NULL DEFAULT 0,
    map_url                  TEXT NOT NULL DEFAULT '',   -- 場地的 Google Maps 連結（前台地點連過去）
    lat                      REAL,                      -- 從連結讀出的座標（app/maps.py），算移動距離用
    lng                      REAL
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
-- status：live 線上、unpublished 取消發佈（上線過、現在下架）、draft 草稿（還沒上線過）。
--   published 跟著 status 走（只有 live 是 1），前台一律看 published。
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
    status          TEXT NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'unpublished', 'draft')),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

-- 網站上的每一頁。kind 決定用哪個版型：
--   home 首頁、performances 演出（列表、統計、歌單、年度回顧四個分頁）、lyrics 歌詞索引、
--   articles 文章列表、article 文章、page 一般內容頁
-- 固定頁面（home、performances、lyrics、articles）各只有一頁，可以改網址但不能刪。
-- slug 是完整路徑、不含前後斜線，例：articles/fanpages；首頁是空字串。
-- status 與 published：同歌詞（live 線上、unpublished 取消發佈、draft 草稿；published 只有 live 是 1）。
-- parent_id 是上層頁面（跟舊站 Wagtail 一樣是一棵樹，首頁是根）。網址＝上層網址＋自己那一段，
-- 由 app/pagetree.py 維護：搬移或改網址時，底下的頁面跟著改，舊網址留下轉址。
-- 歌詞頁的網址＝歌詞索引頁的 slug＋歌詞的 slug；文章同理。
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('home', 'performances', 'lyrics', 'articles', 'article', 'page')),
    parent_id       INTEGER REFERENCES pages(id),
    slug            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    title_en        TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',   -- 列表、搜尋引擎、社群分享用的一句話
    summary_en      TEXT NOT NULL DEFAULT '',
    thumbnail_id    INTEGER REFERENCES images(id) ON DELETE SET NULL,
    body_html       TEXT NOT NULL DEFAULT '',
    body_html_en    TEXT NOT NULL DEFAULT '',
    published       INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'unpublished', 'draft')),
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

-- ==================================================================== 訪客（用 Google 帳號登入的粉絲）
-- 跟後台的 users 完全分開：訪客永遠進不了後台。
-- 個人資料只存登入用得到的：Google 帳號 ID、email、名字、大頭貼。刪除帳號時連同下面所有紀錄一起刪。
CREATE TABLE IF NOT EXISTS visitors (
    id              INTEGER PRIMARY KEY,
    google_sub      TEXT NOT NULL UNIQUE,   -- Google 帳號的永久 ID（email 可能會改，這個不會）
    email           TEXT NOT NULL DEFAULT '',
    google_name     TEXT NOT NULL DEFAULT '',
    avatar_url      TEXT NOT NULL DEFAULT '',
    nickname        TEXT NOT NULL DEFAULT '',   -- 自選暱稱，投稿時可以選用
    handle          TEXT UNIQUE,                -- 公開個人頁的網址 /fans/<handle>/；空白＝沒開
    profile_public  INTEGER NOT NULL DEFAULT 0, -- 1＝公開去過的場次與喜歡的歌
    banned          INTEGER NOT NULL DEFAULT 0, -- 1＝不能再投稿（已投的跑馬燈也不顯示）
    home_district   TEXT NOT NULL DEFAULT '',   -- 選填：住的行政區「縣市|行政區」，算移動路線用；粉絲勾了「記在我的帳號」才存
    created_at      TEXT NOT NULL,
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS visitor_sessions (
    token_hash  TEXT PRIMARY KEY,
    visitor_id  INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

-- 我去過的場次
CREATE TABLE IF NOT EXISTS attendance (
    visitor_id      INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    performance_id  INTEGER NOT NULL REFERENCES performances(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (visitor_id, performance_id)
);
CREATE INDEX IF NOT EXISTS attendance_performance ON attendance(performance_id);

-- 我喜歡的歌
CREATE TABLE IF NOT EXISTS song_likes (
    visitor_id  INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    song_id     INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,     -- 粉絲自己排的順序（「我的 → 喜歡的歌」拖曳排序）
    PRIMARY KEY (visitor_id, song_id)
);
CREATE INDEX IF NOT EXISTS song_likes_song ON song_likes(song_id);

-- 首頁跑馬燈：送出就顯示（hidden＝後台隱藏）。
-- name_mode：google 用 Google 帳號名、nickname 用自選暱稱、anonymous 匿名；顯示時才照目前的名字算。
CREATE TABLE IF NOT EXISTS marquee_posts (
    id          INTEGER PRIMARY KEY,
    visitor_id  INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    name_mode   TEXT NOT NULL DEFAULT 'nickname' CHECK (name_mode IN ('google', 'nickname', 'anonymous')),
    hidden      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    reviewed_at TEXT                -- 管理者在「投稿審核」看過（沒問題、隱藏都算）；空白＝還沒看過
);
CREATE INDEX IF NOT EXISTS marquee_recent ON marquee_posts(hidden, created_at);

-- 演出資訊與歌單的補充：先審後上。payload_json 是使用者填的內容（只放有改的欄位）：
--   {"event_name": "…", "event_name_en": "…", "venue": "…", "venue_en": "…",
--    "setlist": [{"song_id": 3, "custom_title": "", "note": "Encore"}, …], "source": "資料來源", "message": "給管理者的話"}
-- status：pending 待審、approved 已套用、rejected 退回
CREATE TABLE IF NOT EXISTS contributions (
    id              INTEGER PRIMARY KEY,
    visitor_id      INTEGER REFERENCES visitors(id) ON DELETE CASCADE,
    performance_id  INTEGER NOT NULL REFERENCES performances(id) ON DELETE CASCADE,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    admin_note      TEXT NOT NULL DEFAULT '',   -- 退回的原因，投稿者在「我的投稿」看得到
    created_at      TEXT NOT NULL,
    reviewed_at     TEXT
);
CREATE INDEX IF NOT EXISTS contributions_status ON contributions(status, created_at);

-- 新演出的投稿（網站上還沒有的場次）：先審後上。payload_json 是使用者填的內容：
--   {"event_date": "2026-11-01", "event_name": "…", "event_type_id": 1, "city_id": 2, "venue": "…",
--    "setlist": [{"song_id": 3, "custom_title": "", "note": ""}, …]（選填）, "source": "資料來源", "message": "給管理者的話"}
-- 核准時管理者可以先修改，存成一場演出（有附歌單就一起存）；performance_id 記下建立的是哪一場。
CREATE TABLE IF NOT EXISTS show_submissions (
    id              INTEGER PRIMARY KEY,
    visitor_id      INTEGER REFERENCES visitors(id) ON DELETE CASCADE,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    admin_note      TEXT NOT NULL DEFAULT '',
    performance_id  INTEGER REFERENCES performances(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    reviewed_at     TEXT
);
CREATE INDEX IF NOT EXISTS show_submissions_status ON show_submissions(status, created_at);

-- 樂譜投稿：先審後上。圖檔一張以上（sheet_files），或文字譜（text_body），或兩者都有。
-- status：pending 待審、approved 公開、rejected 退回、removed 下架（例如權利人要求）
CREATE TABLE IF NOT EXISTS sheets (
    id          INTEGER PRIMARY KEY,
    visitor_id  INTEGER REFERENCES visitors(id) ON DELETE CASCADE,
    song_id     INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,                  -- 例：吉他和弦譜、鋼琴伴奏
    text_body   TEXT NOT NULL DEFAULT '',
    video_url   TEXT NOT NULL DEFAULT '',
    name_mode   TEXT NOT NULL DEFAULT 'nickname' CHECK (name_mode IN ('google', 'nickname', 'anonymous')),
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'removed')),
    admin_note  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    reviewed_at TEXT,
    delete_requested_at TEXT,                   -- 投稿者在「我的投稿」要求刪除的時間；管理者處理後清空或整筆刪掉
    -- 公開中的樂譜被投稿者修改：修改的內容另存一筆（status＝pending），這裡指向原本那筆。
    -- 核准後這筆取代原本那筆；退回的話原本那筆照樣公開。
    replaces_id INTEGER REFERENCES sheets(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS sheets_song ON sheets(song_id, status);

-- 樂譜的讚（跟歌曲的喜歡分開）
CREATE TABLE IF NOT EXISTS sheet_likes (
    visitor_id  INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    sheet_id    INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (visitor_id, sheet_id)
);
CREATE INDEX IF NOT EXISTS sheet_likes_sheet ON sheet_likes(sheet_id);

CREATE TABLE IF NOT EXISTS sheet_files (
    id        INTEGER PRIMARY KEY,
    sheet_id  INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    file      TEXT NOT NULL,       -- 相對 MEDIA_ROOT，例：sheets/ab12cd.jpg（上傳時重新編碼，去掉照片裡的 GPS 等資訊）
    width     INTEGER,
    height    INTEGER
);

-- 行事曆的放假日（app/holidays.py）：人事行政總處「政府行政機關辦公日曆表」，一天一列
CREATE TABLE IF NOT EXISTS calendar_days (
    date  TEXT PRIMARY KEY,        -- YYYY-MM-DD
    off   INTEGER NOT NULL,        -- 1＝放假（含週末），0＝上班（含補行上班的週六）
    note  TEXT NOT NULL DEFAULT '' -- 國定假日名稱、補假、補行上班……
);
CREATE TABLE IF NOT EXISTS calendar_years (
    year        INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,     -- 人事行政總處／ruyut/TaiwanCalendar／上傳
    url         TEXT NOT NULL DEFAULT '',
    fetched_at  TEXT NOT NULL
);
