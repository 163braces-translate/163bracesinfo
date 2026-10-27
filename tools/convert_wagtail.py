"""把舊站（Wagtail）的 db.sqlite3 轉成新站的 site.sqlite3。

    python -m tools.convert_wagtail 舊站.sqlite3 新站.sqlite3 [--report 報告.md] [--force]

- 舊資料庫只讀，不會被改到；新資料庫已存在時拒絕執行，加 --force 才覆蓋。
- 可以重複執行：先拿本機副本反覆測試，正式切換時再拿當下從 Azure 下載的資料庫跑一次。
- 轉不了、或需要人看一眼的地方都寫進報告，不默默略過。

各類資料怎麼搬：
- 演出、歌單、曲庫、城市、類型、圖片、帳號：一對一照搬，id 沿用。
- 頁面：Wagtail 的中文頁與英文頁是兩筆資料（靠 translation_key 配對），這裡併成一列，英文放 _en 欄位。
  內文（StreamField）轉成一般 HTML，內部連結 linktype="page" 換成新網址。
- 舊歌詞頁（一般頁面做的）：中文頁一行一個 <p>；英文頁同一行寫成「中文 (English)」。
  逐行拆出英文放右欄，左欄一律用中文頁的版本。兩邊中文不一樣、或行數對不上的，列進報告。
"""
import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
from html import escape as _escape, unescape


def escape(s):
    return _escape(s, quote=False)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db  # noqa: E402

# 舊站的城市名稱 → 地圖上的縣市代號（app/taiwan.py）。不在這裡的城市（例如「海外」）不畫在地圖上。
CITY_MAP_KEYS = {
    "台北市": "taipei", "新北市": "new-taipei", "基隆市": "keelung", "桃園市": "taoyuan",
    "新竹市": "hsinchu-city", "新竹縣": "hsinchu", "苗栗縣": "miaoli", "台中市": "taichung",
    "彰化縣": "changhua", "南投縣": "nantou", "雲林縣": "yunlin", "嘉義市": "chiayi-city",
    "嘉義縣": "chiayi", "台南市": "tainan", "高雄市": "kaohsiung", "屏東縣": "pingtung",
    "宜蘭縣": "yilan", "花蓮縣": "hualien", "台東縣": "taitung", "澎湖縣": "penghu",
    "金門縣": "kinmen", "連江縣（馬祖）": "lienchiang", "連江縣": "lienchiang",
}



class Report:
    def __init__(self):
        self.counts = []      # (項目, 數量)
        self.notes = []       # 需要注意的事
        self.lyrics = []      # 每首歌詞的轉換結果（markdown）

    def note(self, text):
        self.notes.append(text)

    def render(self, src):
        out = ["# 舊站資料轉換報告", "", "來源：`%s`" % src, "", "## 搬了什麼", "",
               "| 項目 | 數量 |", "|---|---:|"]
        out += ["| %s | %s |" % c for c in self.counts]
        out += ["", "## 需要注意", ""]
        out += ["- " + n for n in self.notes] or ["（沒有）"]
        out += ["", "## 歌詞逐首檢查", "",
                "⚠️ 的項目也記在那份歌詞上，後台會提醒，確認後按「已確認」。",
                "「中文不同」：英文頁裡的中文跟中文頁不一樣，左欄用的是中文頁的版本，請確認哪個才對。",
                "「沒有配對」：兩邊行數對不上，這幾行找不到對應的另一邊。", ""]
        out += self.lyrics
        return "\n".join(out) + "\n"


# ==================================================================== 富文字
def youtube_id(url):
    m = re.search(r"(?:youtu\.be/|v=|/embed/|/shorts/|/live/)([\w-]{11})", url or "")
    return m.group(1) if m else None


def video_html(url):
    vid = youtube_id(url)
    if not vid:
        return '<p><a href="%s">%s</a></p>' % (_escape(url), escape(url))
    return ('<iframe class="ql-video" frameborder="0" allowfullscreen="true" '
            'src="https://www.youtube-nocookie.com/embed/%s"></iframe>' % vid)


def image_html(image_id, alt=""):
    return '<p><img src="/images/%d/w1200/" alt="%s"></p>' % (image_id, _escape(alt or ""))


class Converter:
    def __init__(self, old, new, report):
        self.old, self.new, self.report = old, new, report
        self.page_urls = {}       # 舊頁面 id → 新網址（中文頁、英文頁各自的）
        self.images = {r["id"] for r in old.execute("SELECT id FROM images_customimage")}

    def rich(self, html):
        """Wagtail 的富文字 → 一般 HTML。"""
        if not html:
            return ""
        html = re.sub(r'\s*data-block-key="[^"]*"', "", html)

        def page_link(m):
            pid = int(m.group(1))
            url = self.page_urls.get(pid)
            if not url:
                self.report.note("內文連到舊頁面 id=%d，但那頁沒有被轉過來，連結改成首頁。" % pid)
                url = "/"
            return '<a href="%s">' % url
        html = re.sub(r'<a linktype="page" id="(\d+)">', page_link, html)

        def embed(m):
            iid = re.search(r'id="(\d+)"', m.group(0))
            alt = re.search(r'alt="([^"]*)"', m.group(0))
            if iid and int(iid.group(1)) in self.images:
                return image_html(int(iid.group(1)), unescape(alt.group(1)) if alt else "")
            self.report.note("內文有無法辨識的嵌入：`%s`" % _escape(m.group(0)[:80]))
            return ""
        html = re.sub(r"<embed [^>]*/?>", embed, html)
        html = html.replace("<b>", "<strong>").replace("</b>", "</strong>")
        html = html.replace("<i>", "<em>").replace("</i>", "</em>")
        # 圖片嵌在段落裡會變成 <p><p><img></p></p>，攤平
        html = re.sub(r"<p>\s*(<p><img [^>]*></p>)\s*</p>", r"\1", html)
        return html

    def stream(self, raw, where):
        """StreamField JSON → 一般 HTML。"""
        if not raw:
            return ""
        blocks = json.loads(raw) if isinstance(raw, str) else raw
        out = []
        for b in blocks:
            t, v = b["type"], b["value"]
            if t == "section":
                if v.get("heading"):
                    out.append("<h2>%s</h2>" % escape(v["heading"]))
                out.append(self.stream(v.get("content") or [], where))
            elif t == "paragraph":
                out.append(self.rich(v))
            elif t == "image":
                if v.get("image") in self.images:
                    out.append(image_html(v["image"], v.get("image_alt_text")))
                    if v.get("caption"):
                        out.append("<p><em>%s</em></p>" % escape(v["caption"]))
            elif t == "youtube":
                if v.get("title"):
                    out.append("<h3>%s</h3>" % escape(v["title"]))
                out.append(video_html(v.get("youtube_url")))
            elif t == "cta":
                out.append("<h3>%s</h3>" % escape(v.get("heading") or ""))
                if v.get("description"):
                    out.append("<p>%s</p>" % escape(v["description"]))
                for link in v.get("link") or []:
                    lv = link["value"]
                    href = lv.get("link") or self.page_urls.get(lv.get("page"), "/")
                    out.append('<p><a href="%s">%s →</a></p>' % (_escape(href), escape(lv.get("title") or href)))
            elif t == "table":
                rows = v.get("data") or []
                rows = [r for r in rows if any(c not in (None, "") for c in r)]
                cells = []
                for i, r in enumerate(rows):
                    tag = "th" if i == 0 and v.get("first_row_is_table_header") else "td"
                    cells.append("<tr>%s</tr>" % "".join(
                        "<%s>%s</%s>" % (tag, escape(c or ""), tag) for c in r))
                out.append("<table>%s</table>" % "".join(cells))
                self.report.note("%s 有表格，已轉成一般表格；之後在編輯器裡只能改文字，不能增減欄列。" % where)
            elif t == "statistics":
                continue          # 首頁的數字區塊另外轉成設定（home_facts_json）
            else:
                self.report.note("%s 有不認得的區塊類型 `%s`，沒有轉過來。" % (where, t))
        return "\n".join(x for x in out if x)


# ==================================================================== 歌詞
def split_title(title):
    """「泥潭 / Mud Puddle」→ ("泥潭", "Mud Puddle")。沒有斜線就整個當中文標題。"""
    parts = re.split(r"\s+/\s*|\s*/\s+", title, maxsplit=1)
    # 斜線後面還有中文就不是英文標題，例如「[粉專] 各粉絲專頁 / LINE社群介紹」
    if len(parts) == 2 and not has_cjk(parts[1]):
        return parts[0].strip(), parts[1].strip()
    return title.strip(), ""


def paragraphs(html):
    return [unescape(re.sub(r"<[^>]+>", "", p)).strip()
            for p in re.findall(r"<p[^>]*>(.*?)</p>", html or "", re.S)]


def has_latin(s):
    return bool(re.search(r"[A-Za-z]", s))


def has_cjk(s):
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", s))


def trailing_group(s):
    """行尾最後一組括號（半形或全形）：("前面", "括號裡")；行尾不是括號就回 None。"""
    s = s.rstrip()
    if not s or s[-1] not in ")）":
        return None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] in ")）":
            depth += 1
        elif s[i] in "(（":
            depth -= 1
            if depth == 0:
                return s[:i].rstrip(), s[i + 1:-1].strip()
    return None


def unwrap(s):
    g = trailing_group(s)
    return g[1] if g and not g[0] else s


def split_en_line(e, z=None):
    """英文頁的一行 → (中文部分, 英文翻譯)。z 是中文頁對應的那一行（知道的話）。"""
    e = e.strip()
    if z is not None and e == z:
        return z, ""
    if z and e.startswith(z):
        return z, unwrap(e[len(z):].strip())
    g = trailing_group(e)
    if g and g[0] and has_latin(g[1]):
        return g
    if not has_cjk(e):
        return "", e          # 整行都是英文：可能是翻過的說明文字，也可能本來就是英文歌詞
    return e, ""


def norm(s):
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def stream_lines(raw):
    """舊歌詞頁的內文 → [(段落標題, 段落標題英文, [行…])], [影片]。空的 <p> 是段落分隔，以 "" 表示。"""
    blocks, videos = [], []
    for b in json.loads(raw or "[]"):
        if b["type"] != "section":
            continue
        lines = []
        for cb in b["value"].get("content") or []:
            if cb["type"] == "paragraph":
                lines += paragraphs(cb["value"])
            elif cb["type"] == "youtube":
                videos.append(cb["value"])
        blocks.append((b["value"].get("heading") or "", lines))
    return blocks, videos


def to_sections(pairs, name="", name_alt=""):
    """[(左, 右)…]，(None, None) 是分段 → sections_json 的段落。"""
    def section(name="", name_alt=""):
        return {"type": "section", "name": name, "name_alt": name_alt, "lines": []}
    sections, cur = [], section(name, name_alt)
    for left, right in pairs:
        if left is None:
            if cur["lines"]:
                sections.append(cur)
            cur = section()
        else:
            cur["lines"].append({"left": left, "right": right})
    if cur["lines"]:
        sections.append(cur)
    return sections


def align(zh, en, issues):
    """中文頁的行與英文頁的行逐行配對。回傳 [(左, 右)…]，分段以 (None, None) 表示。"""
    def is_break(s):
        return not s.strip()

    pairs = []
    if len(zh) == len(en):
        matches = [(z, e) for z, e in zip(zh, en)]
    else:
        keys_z = [norm(z) for z in zh]
        keys_e = [norm(split_en_line(e)[0]) for e in en]
        matches = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, keys_z, keys_e, autojunk=False).get_opcodes():
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
                matches += list(zip(zh[i1:i2], en[j1:j2]))
            else:
                for z in zh[i1:i2]:
                    matches.append((z, None))
                    if not is_break(z):
                        issues.append("沒有配對（只有中文頁有）：%s" % z)
                for e in en[j1:j2]:
                    matches.append((None, e))
                    if not is_break(e):
                        issues.append("沒有配對（只有英文頁有）：%s" % e)

    for z, e in matches:
        if (z is None or is_break(z)) and (e is None or is_break(e)):
            pairs.append((None, None))
            continue
        if e is None:
            pairs.append((z, ""))
            continue
        ez, right = split_en_line(e, z)
        if z is None:
            pairs.append((ez, right))
            continue
        if ez and norm(ez) != norm(z):
            issues.append("中文不同：中文頁「%s」／英文頁「%s」" % (z, ez))
        elif not ez and right and has_cjk(z):
            # 英文頁整行換成英文（例如說明文字的翻譯）
            pass
        pairs.append((z, right))
    return pairs


# ==================================================================== 主流程
def convert(old_path, new_path, force=False):
    if os.path.exists(new_path):
        if not force:
            sys.exit("%s 已經存在。確定要覆蓋就加 --force。" % new_path)
        os.remove(new_path)

    old = db.connect(os.path.abspath(old_path), readonly=True)
    new = db.connect(new_path)
    db.init(new)
    report = Report()
    conv = Converter(old, new, report)
    stamp = db.now()

    # ---- 圖片、帳號
    n = 0
    for r in old.execute("SELECT id, file, title, width, height, created_at FROM images_customimage"):
        new.execute("INSERT INTO images VALUES (?, ?, ?, ?, ?, ?)",
                    (r["id"], r["file"], r["title"], r["width"], r["height"], r["created_at"][:19]))
        n += 1
    report.counts.append(("圖片", n))

    n = 0
    for r in old.execute("SELECT * FROM users_user WHERE is_staff = 1 OR is_superuser = 1"):
        new.execute("INSERT INTO users (id, username, password, is_active, last_login, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (r["id"], r["username"], r["password"], r["is_active"],
                     (r["last_login"] or "")[:19] or None, r["date_joined"][:19]))
        n += 1
    report.counts.append(("後台帳號（密碼照舊可用）", n))
    skipped = old.execute("SELECT COUNT(*) FROM users_user WHERE is_staff = 0 AND is_superuser = 0").fetchone()[0]
    if skipped:
        report.note("有 %d 個非後台帳號沒有轉過來（新站只有後台需要登入）。" % skipped)

    # ---- 演出資料、曲庫
    for r in old.execute('SELECT id, name, name_en, "order" FROM performances_eventtype'):
        new.execute("INSERT INTO event_types VALUES (?, ?, ?, ?)", tuple(r))
    for r in old.execute('SELECT id, name, name_en, "order" FROM performances_city'):
        key = CITY_MAP_KEYS.get(r["name"], "")
        if not key:
            report.note("城市「%s」沒有對應的地圖縣市，不會畫在地圖上。" % r["name"])
        new.execute("INSERT INTO cities VALUES (?, ?, ?, ?, ?)", (r["id"], r["name"], r["name_en"], key, r["order"]))
    for r in old.execute('SELECT id, name, name_en, "order", cover_image_id FROM performances_album'):
        new.execute("INSERT INTO albums (id, name, name_en, cover_image_id, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (r["id"], r["name"], r["name_en"], r["cover_image_id"], r["order"]))
    for r in old.execute('SELECT * FROM performances_song'):
        new.execute("INSERT INTO songs (id, title, title_en, artist, artist_en, album_id, cover_image_id, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["id"], r["title"], r["title_en"], r["artist"], r["artist_en"], r["album_id"],
                     r["single_image_id"], r["order"]))
    for r in old.execute("SELECT * FROM performances_performance"):
        new.execute("INSERT INTO performances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["id"], r["event_date"], r["event_name"], r["event_name_en"], r["event_type_id"],
                     r["venue"], r["venue_en"], r["city_id"], r["setlist_order_uncertain"]))
    for r in old.execute("SELECT * FROM performances_setlistitem ORDER BY performance_id, sort_order, id"):
        new.execute("INSERT INTO setlist_items VALUES (?, ?, ?, ?, ?, ?)",
                    (r["id"], r["performance_id"], r["sort_order"] or 0, r["song_id"],
                     "" if r["song_id"] else r["custom_title"], r["note"]))
    for table, label in [("event_types", "演出類型"), ("cities", "城市"), ("performances", "演出"),
                         ("setlist_items", "歌單曲目"), ("albums", "專輯"), ("songs", "歌曲")]:
        report.counts.append((label, new.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]))

    # ---- 頁面樹：先算出每一頁的新網址，內文的內部連結才換得過去
    pages = [dict(r) for r in old.execute("""
        SELECT p.id, p.title, p.slug, p.url_path, p.live, p.translation_key, p.depth,
               p.first_published_at, ct.model, l.language_code AS lang
        FROM wagtailcore_page p
        JOIN django_content_type ct ON ct.id = p.content_type_id
        JOIN wagtailcore_locale l ON l.id = p.locale_id
        WHERE p.depth >= 2 ORDER BY p.path""")]
    for p in pages:
        rel = "/".join(p["url_path"].strip("/").split("/")[1:])   # 去掉第一層（/home/、/home-1/）
        p["rel"] = rel
        new_rel = rel + "/" if rel else ""
        prefix = "/en/" if p["lang"] == "en" else "/"
        conv.page_urls[p["id"]] = prefix + new_rel
    by_key = {}
    for p in pages:
        by_key.setdefault(p["translation_key"], {})[p["lang"]] = p

    def detail(table, pid):
        return old.execute("SELECT * FROM %s WHERE page_ptr_id = ?" % table, (pid,)).fetchone()

    def add_page(kind, slug, zh, en, table, body_fn, summary_fn=None, thumb=None, published_at=None, order=0):
        dz = detail(table, zh["id"])
        de = detail(table, en["id"]) if en else None
        t_zh, t_en = split_title(zh["title"])
        if en and not t_en:
            t_en = split_title(en["title"])[1] or en["title"]
        where = "頁面「%s」" % zh["title"]
        new.execute(
            "INSERT INTO pages (kind, slug, title, title_en, summary, summary_en, thumbnail_id, body_html, "
            "body_html_en, published, published_at, sort_order, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, slug, t_zh, t_en if t_en != t_zh else "",
             summary_fn(dz) if summary_fn else "", summary_fn(de) if summary_fn and de else "",
             thumb(dz) if thumb else None, body_fn(dz, where), body_fn(de, where + "（英文）") if de else "",
             1 if zh["live"] else 0, published_at, order, stamp))

    def plain(html):
        return unescape(re.sub(r"<[^>]+>", " ", html or "")).strip()

    seen_kinds = set()
    lyrics_pages = []
    for p in pages:
        if p["lang"] != "zh-hant":
            continue
        en = by_key.get(p["translation_key"], {}).get("en")
        m = p["model"]
        if m == "homepage":
            add_page("home", "", p, en, "home_homepage",
                     lambda d, w: conv.stream(d["body"], w),
                     summary_fn=lambda d: d["introduction"],
                     thumb=lambda d: next((b["value"]["image"] for b in json.loads(d["hero_image"] or "[]")), None))
            home_row = detail("home_homepage", p["id"])
            hero = next((b["value"]["image"] for b in json.loads(home_row["hero_image"] or "[]")), None)
            if hero:
                db.set_setting(new, "home_hero_image_id", hero)
                db.set_setting(new, "home_hero_mode", "cover")
                db.set_setting(new, "home_hero_overlay", 100 - (home_row["bg_opacity"] or 0))
                if home_row["bg_display_mode"] != "cover":
                    report.note("舊站首頁背景是「%s」顯示，新站只有滿版與右半邊兩種，先用滿版。" % home_row["bg_display_mode"])
            stats = json.loads(home_row["body"] or "[]")
            facts = []
            for b in stats:
                if b["type"] == "statistics":
                    for item in b["value"]["statistics"]:
                        s = old.execute("SELECT * FROM utils_statistic WHERE id = ?", (item["value"],)).fetchone()
                        if s:
                            facts.append({"value": s["statistic"], "value_en": s["statistic_en"],
                                          "label": s["description"], "label_en": s["description_en"]})
            db.set_setting(new, "home_facts_json", json.dumps(facts, ensure_ascii=False))
            report.note("首頁的「一些有趣的數據」（YouTube 觀看數等 %d 項）是手動填的數字，已搬到設定，"
                        "後台可以改；要不要放在新首頁可以再決定。" % len(facts))
        elif m == "performancelistpage":
            add_page("performances", p["rel"], p, en, "performances_performancelistpage",
                     lambda d, w: conv.rich(d["intro"]), order=1)
        # 統計、歌單、年度回顧在新站是演出頁的分頁，網址照舊（/performances/stats/、/performances/setlist/、
        # /replay/），所以只搬說明文字與設定，不建頁面也不用轉址
        elif m == "performancestatspage":
            db.set_setting(new, "charts_intro_html", conv.rich(detail("performances_performancestatspage", p["id"])["intro"]))
            if en:
                db.set_setting(new, "charts_intro_html_en",
                               conv.rich(detail("performances_performancestatspage", en["id"])["intro"]))
        elif m == "setlistprogresspage":
            d = detail("performances_setlistprogresspage", p["id"])
            db.set_setting(new, "setlist_intro_html", conv.rich(d["intro"]))
            db.set_setting(new, "show_donation_call", d["show_donation_call"])
            db.set_setting(new, "donation_amount", d["donation_amount"])
            db.set_setting(new, "setlist_top_songs_count", d["top_songs_count"])
        elif m == "replaypage":
            d = detail("performances_replaypage", p["id"])
            db.set_setting(new, "replay_intro_html", conv.rich(d["intro"]))
            db.set_setting(new, "replay_logo_id", d["logo_id"] or "")
        elif m == "newslistingpage":
            add_page("articles", p["rel"], p, en, "news_newslistingpage",
                     lambda d, w: conv.rich(d["introduction"]) if "introduction" in d.keys() else "",
                     order=4)
        elif m == "articlepage":
            add_page("article", p["rel"], p, en, "news_articlepage",
                     lambda d, w: conv.stream(d["image"], w) + "\n" + conv.stream(d["body"], w),
                     summary_fn=lambda d: d["introduction"] or d["listing_summary"],
                     thumb=lambda d: d["listing_image_id"],
                     published_at=(detail("news_articlepage", p["id"])["publication_date"] or "")[:10] or None)
        elif m == "indexpage" and p["rel"] == "lyrics":
            add_page("lyrics", p["rel"], p, en, "standardpages_indexpage",
                     lambda d, w: conv.rich(d["introduction"]), order=3)
            report.note("歌詞索引頁原本手動列出各專輯的歌（有序清單），新站改成依專輯自動排列，"
                        "那段清單沒有轉過來；排列順序照舊清單排好了。")
        elif m == "indexpage" or m == "standardpage" and not p["rel"].startswith("lyrics/"):
            table = "standardpages_indexpage" if m == "indexpage" else "standardpages_standardpage"
            add_page("page", p["rel"], p, en, table,
                     lambda d, w: conv.rich(d["introduction"]) + "\n" + conv.stream(d["body"], w),
                     thumb=lambda d: d["listing_image_id"], order=5)
            if not p["live"]:
                report.note("頁面「%s」在舊站是未發佈狀態，轉過來也是未發佈。" % p["title"])
        elif p["rel"].startswith("lyrics/"):
            lyrics_pages.append((p, en))
        else:
            report.note("頁面「%s」（%s）沒有轉過來：不認得的頁面類型。" % (p["title"], m))
        seen_kinds.add(m)
    report.counts.append(("頁面", new.execute("SELECT COUNT(*) FROM pages").fetchone()[0]))

    convert_lyrics(conv, old, new, report, lyrics_pages, pages, stamp)

    # 頁首選單與頁尾：依轉過來的頁面產生預設的一份，之後在後台「頁首與頁尾」改
    from app import navigation
    db.set_setting(new, navigation.HEADER_KEY, json.dumps(navigation.default_header(new), ensure_ascii=False))
    db.set_setting(new, navigation.FOOTER_KEY, json.dumps(navigation.default_footer(new), ensure_ascii=False))

    # ---- 轉址：只搬舊站後台設的（網址都沿用舊站，不需要另外轉）
    for r in old.execute("SELECT * FROM wagtailredirects_redirect"):
        target = r["redirect_link"] or conv.page_urls.get(r["redirect_page_id"])
        source = r["old_path"].rstrip("/") + "/"
        if target and target != source:      # 指向自己的轉址會無限循環
            new.execute("INSERT OR REPLACE INTO redirects VALUES (?, ?)", (source, target))
    report.counts.append(("轉址", new.execute("SELECT COUNT(*) FROM redirects").fetchone()[0]))

    new.commit()
    problems = new.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        report.note("⚠️ 外鍵檢查有 %d 筆問題：%s" % (len(problems), [tuple(p) for p in problems[:5]]))
    return report


def convert_lyrics(conv, old, new, report, lyrics_pages, pages, stamp):
    songs = list(new.execute("SELECT * FROM songs"))

    # 舊歌詞索引頁的有序清單決定歌詞的排列順序
    order = {}
    idx = old.execute("SELECT x.body FROM standardpages_indexpage x JOIN wagtailcore_page p ON p.id = x.page_ptr_id "
                      "JOIN wagtailcore_locale l ON l.id = p.locale_id "
                      "WHERE p.slug = 'lyrics' AND l.language_code = 'zh-hant'").fetchone()
    if idx:
        for i, pid in enumerate(re.findall(r'linktype=\\?"page\\?" id=\\?"(\d+)', idx["body"] or "")):
            order.setdefault(int(pid), i + 1)

    en_by_slug = {p["slug"]: p for p in pages if p["lang"] == "en" and p["rel"].startswith("lyrics/")}
    n_ok = 0
    for zh, en in lyrics_pages:
        if not en and zh["slug"] in en_by_slug:
            en = en_by_slug[zh["slug"]]      # 歌詞頁改版時重建過頁面，translation_key 對不上，改用網址配對
        issues = []   # 要人確認的（寫進 review_json，後台會提醒）
        info = []     # 只寫在報告裡
        title, title_en = split_title(zh["title"])
        if zh["model"] == "lyricspage":
            d = old.execute("SELECT * FROM lyrics_lyricspage WHERE page_ptr_id = ?", (zh["id"],)).fetchone()
            sections = []
            for b in json.loads(d["body"] or "[]"):
                if b["type"] == "section":
                    v = b["value"]
                    sections.append({"type": "section",
                                     "name": v.get("section_name") or "", "name_alt": v.get("section_name_alt") or "",
                                     "lines": [{"left": ln["value"].get("left") or "",
                                                "right": ln["value"].get("right") or ""} for ln in v["lines"]]})
                elif b["type"] == "note":
                    sections.append({"type": "note", "html": conv.rich(b["value"])})
            has_right = any(ln["right"] for s in sections for ln in s.get("lines", []))
            videos = []
            if en and en["model"] == "standardpage" and not has_right:
                # 中文是新版歌詞頁、英文還是舊的一般頁面：把英文頁的翻譯對進來
                en_blocks, _ = stream_lines(old.execute("SELECT body FROM standardpages_standardpage "
                                                        "WHERE page_ptr_id = ?", (en["id"],)).fetchone()[0])
                zh_lines = []
                for s in sections:
                    if s["type"] == "section":
                        zh_lines += [ln["left"] for ln in s["lines"]] + [""]
                en_lines = [ln for _, lines in en_blocks for ln in lines + [""]]
                pairs = align(zh_lines[:-1], en_lines[:-1], issues)
                notes = [s for s in sections if s["type"] == "note"]
                sections = to_sections(pairs, sections[0]["name"] if sections else "") + notes
                info.append("中文是新版歌詞頁、英文是舊頁面，已把英文頁的翻譯逐行對進來。")
            row = dict(mode=d["display_mode"], left=d["left_label"], right=d["right_label"],
                       artist=d["artist"], composer=d["composer"], lyricist=d["lyricist"], year=d["release_year"],
                       intro="", intro_en="")
        else:
            dz = old.execute("SELECT * FROM standardpages_standardpage WHERE page_ptr_id = ?", (zh["id"],)).fetchone()
            de = old.execute("SELECT * FROM standardpages_standardpage WHERE page_ptr_id = ?",
                             (en["id"],)).fetchone() if en else None
            zb, videos = stream_lines(dz["body"])
            eb, en_videos = stream_lines(de["body"]) if de else ([], [])
            for v, ev in zip(videos, en_videos):
                if ev.get("title") and ev["title"] != v.get("title"):
                    v["title_en"] = ev["title"]
            sections = []
            for i, (heading, zl) in enumerate(zb):
                eh, el = eb[i] if i < len(eb) else ("", [])
                if de is None:
                    pairs = [(None, None) if not z.strip() else (z, "") for z in zl]
                else:
                    if i >= len(eb):
                        issues.append("英文頁少了段落「%s」" % heading)
                    pairs = align(zl, el, issues)
                if heading:
                    # 帶標題的段落是補充、舊版本、創作理念這類非主要歌詞，放進另一個方框
                    sections.append({"type": "part", "title": heading, "title_en": eh if eh != heading else ""})
                sections += to_sections(pairs)
            if de is None:
                info.append("沒有英文頁，只有中文。")
            n_right = sum(1 for s in sections for ln in s.get("lines", []) if ln["right"])
            row = dict(mode="bilingual" if n_right else "single", left="中文", right="English",
                       artist="", composer="", lyricist="", year=None,
                       intro=conv.rich(dz["introduction"]), intro_en=conv.rich(de["introduction"]) if de else "")
            parts = [h for h, _ in zb if h]
            if parts:
                info.append("帶標題的段落（%s）放進另一個方框。" % "、".join(parts))

        lyrics_id = new.execute(
            "INSERT INTO lyrics (slug, title, title_en, artist, composer, lyricist, release_year, "
            "display_mode, left_label, right_label, intro_html, intro_html_en, sections_json, videos_json, "
            "review_json, published, sort_order, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (zh["slug"], title, title_en, row["artist"], row["composer"], row["lyricist"], row["year"],
             row["mode"], row["left"], row["right"], row["intro"], row["intro_en"],
             json.dumps(sections, ensure_ascii=False),
             json.dumps([{"title": v.get("title") or "", "title_en": v.get("title_en") or "",
                          "url": v.get("youtube_url") or ""} for v in videos], ensure_ascii=False),
             json.dumps([{"message": i} for i in issues], ensure_ascii=False),
             1 if zh["live"] else 0, order.get(zh["id"], 1000 + zh["id"]), stamp)).lastrowid

        # 曲名一樣的歌曲指向這份歌詞；對不到的在後台「歌曲 ↔ 歌詞」手動對應
        matched = [s for s in songs if norm(s["title"]) == norm(title)]
        for song in matched:
            new.execute("UPDATE songs SET lyrics_id = ? WHERE id = ?", (lyrics_id, song["id"]))
            if title_en and not song["title_en"]:
                new.execute("UPDATE songs SET title_en = ? WHERE id = ?", (title_en, song["id"]))
            if videos and not song["listen_url"]:
                new.execute("UPDATE songs SET listen_url = ? WHERE id = ?", (videos[0]["youtube_url"], song["id"]))
        if not matched:
            info.append("沒有曲名相同的歌曲，要在後台「歌曲 ↔ 歌詞」手動對應。")

        n_lines = sum(len(s.get("lines", [])) for s in sections)
        n_right = sum(1 for s in sections for ln in s.get("lines", []) if ln["right"])
        status = "✅" if not issues else "⚠️"
        report.lyrics.append("### %s %s　`/lyrics/%s/`" % (status, zh["title"], zh["slug"]))
        report.lyrics.append("")
        report.lyrics.append("%d 行，其中 %d 行有右欄；影片 %d 支；%s" % (
            n_lines, n_right, len(videos),
            "對到曲庫「%s」" % "、".join(m["title"] for m in matched) if matched else "**沒有對到曲庫**"))
        report.lyrics += [""] + ["- ⚠️ " + i for i in issues] + ["- " + i for i in info] + [""]
        if not issues:
            n_ok += 1
    report.counts.append(("歌詞（不需人工檢查／全部）", "%d／%d" % (n_ok, len(lyrics_pages))))
    unlinked = [r["title"] for r in new.execute(
        "SELECT title FROM songs WHERE lyrics_id IS NULL ORDER BY sort_order")]
    if unlinked:
        report.note("這些歌還沒對應到歌詞（後台「歌曲 ↔ 歌詞」可以手動對應）：%s" % "、".join(unlinked))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--report", help="報告輸出路徑（預設：新資料庫旁邊的 convert_report.md）")
    ap.add_argument("--force", action="store_true", help="新資料庫已存在時覆蓋")
    args = ap.parse_args()
    report = convert(args.old, args.new, args.force)
    path = args.report or os.path.join(os.path.dirname(os.path.abspath(args.new)), "convert_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.render(args.old))
    print("完成：%s\n報告：%s" % (args.new, path))


if __name__ == "__main__":
    main()
