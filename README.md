# 163braces 資訊站

163braces 的中英雙語資訊站，以 Wagtail CMS 建置。
核心是**演出資料庫**（`performances`）—— 收錄其歷年演出紀錄與歌單，提供查詢、統計圖表與年度回顧。

- 正式站：<https://163braces.info>
- 技術堆疊：Django 4.2 + Wagtail 6.4 + Tailwind CSS + SQLite
- 部署：Azure App Service（GitHub Actions 自動部署）

---

## 演出功能（performances）

這是本站的主體。四個頁面共用同一份演出資料，各自針對不同的使用情境。

### 1. 演出列表 `/performances/`

以表格呈現全部演出紀錄，欄位為：日期、活動名稱、類型、地點、城市。

日期會一併顯示星期（中文 `2026/09/06 (日)`、英文 `(Sun.)`），由 `event_date` 當場計算，沒有另存欄位。

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

**歌單展開**

有歌單的場次，活動名稱會變成可點擊的按鈕，後面帶一個 `♪` 加曲目數的徽章。點一下在該列下方展開歌單，再點一次收合。沒有歌單的場次維持純文字。

若該場次在後台被勾選「不確定順序」，徽章會改用淺黃色，展開後另有一行「⚠️ 此場次曲序不確定」。

> 沒有用 hover 觸發，因為手機沒有 hover。

> **注意**：此頁目前**沒有分頁**，會一次載入全部演出。資料量大幅成長時需要留意。

### 2. 演出統計 `/performances/stats/`

用 Chart.js 呈現六張圖表。頁面上方兩張涵蓋所有年份，下方四張跟著年份選擇器變動（`?year=2025` 或 `?year=all`）。

| 圖表 | 型態 | 內容 | 受年份篩選 |
|---|---|---|---|
| 歷史演出統計 | 堆疊長條圖 | 全部歷史的逐月演出數，依類型堆疊 | 否 |
| 各類型累積演出場次 | 折線圖 | 每個類型的場次逐月累加 | 否 |
| 各類型月度演出統計 | 堆疊長條圖 | 選定年份中，各類型在 1–12 月的演出數 | 是 |
| 城市演出比例 | 圓餅圖 | 各城市演出場次占比 | 是 |
| 各類型星期分布 | 堆疊長條圖 | 週一到週日的場次，依類型堆疊 | 是 |
| 星期演出比例 | 圓餅圖 | 各星期占比，由多到少排序 | 是 |

### 3. 歌單募集 `/performances/setlist/`

募集缺漏歌單的頁面，同時呈現已收集資料能看出的東西。

| 區塊 | 內容 |
|---|---|
| 進度條 | 已填歌單的場次占比。**只計算已發生的演出** —— 未來的場次不可能有歌單，計入會低估進度 |
| 捐款號召 | 黃色方框，金額與是否顯示都可在後台設定 |
| 各歌曲累積演出次數 | 折線圖，預設前 10 名，可切換為全部 |
| 各類型每場曲目數 | 表格：最少／平均／中位數／最多，以及各端點的場次 |

表格排除曲目數 2 首（含）以下的場次，視為離群值 —— 一兩首通常是短暫嘉賓之類的特例，跟一般演出不是同一回事。若某類型所有場次都低於門檻，該類型不會出現在表格裡。

並列時取**最新**的一場，並標示「另有 X 場並列」。

> 這個頁面不會自動存在。程式碼提供的是頁面**類型**，實際頁面是 Wagtail 資料：後台 → Pages → 演出 / Performances → Add child page → 「歌單募集頁」，slug 填 `setlist`。

### 4. 年度回顧 `/replay/`

讓粉絲自行製作年度回顧卡片的互動頁面，流程為：填名字 → 選歌曲 → 選當年參與過的演出 → 留言 → 產生圖片下載。

整張卡片以 Canvas 在瀏覽器端繪製後輸出 PNG，**不會將任何輸入回傳伺服器**，因此沒有留言的儲存或審核機制。

---

## 資料模型

演出資料以 Wagtail **Snippet** 管理，在後台「程式碼片段（Snippets）」中維護，不需要改程式。

```
Performance（演出紀錄）
├── event_date              演出日期
├── event_name              活動名稱     + event_name_en
├── venue                   地點         + venue_en
├── event_type              ─→ EventType（類型）
├── city                    ─→ City（城市）
├── setlist_order_uncertain 曲序是否未確認（勾選框）
└── setlist                 ─→ SetlistItem（可排序的曲目清單）

SetlistItem（歌單的一行）
├── song          ─→ Song      從曲庫選，或
├── custom_title  自訂曲名      翻唱、曲庫沒有的歌
├── note          備註          例如 Cover、Encore
└── sort_order    順序          後台可拖曳

Album（專輯）──┐
               ├─ Song（歌曲，供歌單與 replay 頁選取）
               └─ cover_image / single_image
```

| Snippet | 用途 | 欄位重點 |
|---|---|---|
| `EventType` | 演出類型 | 校唱、商演、專場、音樂祭、演講 |
| `City` | 城市 | 台北市、新北市、桃園市…（`order` 控制下拉選單順序） |
| `Performance` | 單場演出 | 關聯類型與城市，內含歌單 |
| `Album` | 專輯 | 可上傳封面 |
| `Song` | 歌曲 | 隸屬專輯，可另外設定單曲封面 |

`EventType`、`City`、`Album`、`Song` 都有 `order` 欄位，數字越小越前面。

`SetlistItem` 不是獨立的 Snippet，而是附屬在演出底下編輯。`song` 與 `custom_title` 必須擇一填寫 —— 兩個都空或兩個都填都會被擋下來。

### 新增一場演出

後台 → Snippets → Performances → Add，填入日期、名稱、選擇類型與城市即可。類型或城市不存在時，要先到對應的 Snippet 新增。

### 填寫歌單

同一個編輯畫面往下捲到「歌單」，逐首新增曲目：

- 曲庫有的歌 → 從「曲庫歌曲」下拉選單選
- 翻唱或曲庫沒有的 → 留空下拉選單，改填「自訂曲名」
- 需要註記就寫在「備註」，例如 `Cover`、`Encore`
- 順序可直接拖曳，或用上下箭頭調整

若當場順序記不清楚，勾選「不確定順序」，前台會以淺黃色標示。

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

較新的程式碼改用另一種寫法：屬性自己讀取當前語言，模板就不必傳參數。`SetlistItem.display_title` 是這樣寫的：

```python
@property
def display_title(self):
    if self._english and self.song.title_en:
        return self.song.title_en
    ...
```

模板只要寫 `{{ item.display_title }}` 就會自動切換。新增雙語欄位時建議採這種寫法。

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
├── models.py          Snippet 模型與四個頁面類型
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
