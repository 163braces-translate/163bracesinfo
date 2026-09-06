# 163braces 資訊站

163braces 的中英雙語資訊站，以 Wagtail CMS 建置。
核心是**演出資料庫**（`performances`）—— 收錄其歷年演出紀錄，提供查詢、統計圖表與年度回顧。

- 正式站：<https://163braces.info>
- 技術堆疊：Django 4.2 + Wagtail 6.4 + Tailwind CSS + SQLite
- 部署：Azure App Service（GitHub Actions 自動部署）

---

## 演出功能（performances）

這是本站的主體。三個頁面共用同一份演出資料，各自針對不同的使用情境。

### 1. 演出列表 `/performances/`

以表格呈現全部演出紀錄，欄位為：日期、活動名稱、類型、地點、城市。

**篩選與排序**（皆透過網址參數，可自由組合）

| 參數 | 說明 | 範例 |
|---|---|---|
| `q` | 依活動名稱關鍵字搜尋 | `?q=演唱會` |
| `city` | 依城市篩選，可複選 | `?city=1&city=6` |
| `event_type` | 依類型篩選，可複選 | `?event_type=3` |
| `date_filter_type` | 日期模式：`range` / `before` / `after` | `?date_filter_type=after` |
| `date_from` / `date_to` | 日期起訖（`YYYY-MM-DD`） | `?date_from=2025-01-01` |
| `sort` | `event_date_desc`（預設）或 `event_date_asc` | `?sort=event_date_asc` |

日期篩選有三種模式，前端會依選擇動態顯示對應欄位，並防止結束日期早於開始日期。

> **注意**：此頁目前**沒有分頁**，會一次載入全部演出。資料量大幅成長時需要留意。

### 2. 演出統計 `/performances/stats/`

用 Chart.js 呈現三張圖表，可切換年份或選擇「全部時間」（`?year=2025` 或 `?year=all`）。

| 圖表 | 型態 | 內容 |
|---|---|---|
| 每月演出分布 | 堆疊長條圖 | 選定年份中，各類型在 1–12 月的演出數 |
| 城市比例 | 圓餅圖 | 各城市演出場次占比 |
| 歷史趨勢 | 堆疊長條圖 | 不受年份篩選影響，涵蓋全部歷史的逐月統計 |

### 3. 年度回顧 `/replay/`

讓粉絲自行製作年度回顧卡片的互動頁面，流程為：填名字 → 選歌曲 → 選當年參與過的演出 → 留言 → 產生圖片下載。

整張卡片以 Canvas 在瀏覽器端繪製後輸出 PNG，**不會將任何輸入回傳伺服器**，因此沒有留言的儲存或審核機制。

---

## 資料模型

演出資料以 Wagtail **Snippet** 管理，在後台「程式碼片段（Snippets）」中維護，不需要改程式。

```
Performance（演出紀錄）
├── event_date   演出日期
├── event_name   活動名稱     + event_name_en
├── venue        地點         + venue_en
├── event_type   ─→ EventType（類型）
└── city         ─→ City（城市）

Album（專輯）──┐
               ├─ Song（歌曲，供 replay 頁選取）
               └─ cover_image / single_image
```

| Snippet | 用途 | 欄位重點 |
|---|---|---|
| `EventType` | 演出類型 | 校唱、商演、專場、音樂祭、演講 |
| `City` | 城市 | 台北市、新北市、桃園市…（`order` 控制下拉選單順序） |
| `Performance` | 單場演出 | 關聯類型與城市 |
| `Album` | 專輯 | 可上傳封面 |
| `Song` | 歌曲 | 隸屬專輯，可另外設定單曲封面 |

`EventType`、`City`、`Album`、`Song` 都有 `order` 欄位，數字越小越前面。

### 新增一場演出

後台 → Snippets → Performances → Add，填入日期、名稱、選擇類型與城市即可。類型或城市不存在時，要先到對應的 Snippet 新增。

---

## 雙語處理

網站支援繁體中文（預設，無網址前綴）與英文（`/en/` 前綴），由 `wagtail-localize` 處理頁面層級的翻譯。

演出資料的雙語則是**在同一筆資料上並存**：每個名稱欄位都有對應的 `_en` 版本（`event_name` / `event_name_en`）。模板依當前語言決定顯示哪一個，英文欄位留空時**自動退回中文**：

```django
{% if current_language == 'en' and p.event_name_en %}
    {{ p.event_name_en }}
{% else %}
    {{ p.event_name }}
{% endif %}
```

> 模型上另有 `get_name(language=...)` 這類方法，但 Django 模板無法傳參數給方法呼叫，實際上永遠取得預設的中文。**請沿用上面的模板寫法**，不要改用那些方法。

---

## 本機開發

需要 Python 3.9 以上（正式環境為 3.11）與 Node.js 18。

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py collectstatic --noinput   # 必要，靜態檔採用 manifest 機制
python manage.py createsuperuser
python manage.py runserver
```

## 專案結構

```
performances/          演出功能（本站核心）
├── models.py          Snippet 模型與三個頁面類型
└── migrations/
myproject/
├── settings/          base.py（正式環境使用）/ dev.py / production.py
├── news/              文章與文章列表
├── standardpages/     一般內容頁
├── home/              首頁
├── navigation/        選單設定
└── utils/             共用模型、blocks、樣板標籤
lyrics/                歌詞頁（雙欄對照／對唱模式）
templates/pages/       頁面模板
static_src/            前端原始碼（Sass、JS）
static_compiled/       webpack 產出
```
