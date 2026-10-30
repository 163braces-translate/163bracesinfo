"""頁首選單與頁尾，在後台「頁首與頁尾」編輯，存在 settings 表的兩個 JSON：

header_menu_json：選單項目，最多兩層（第二層是下拉選單）
  [{"label": "演出", "label_en": "", "page_id": 2, "url": "",
    "children": [{"label": "演出統計", "label_en": "Charts", "page_id": null, "url": "/performances/stats/"}]}]

footer_json：頁尾，欄位數不限
  {"columns": [{"title": "…", "title_en": "…", "text": "…", "text_en": "…", "links": [連結, …]}],
   "note": "最下面一行", "note_en": "…"}

連結的兩種寫法：
- page_id：連到網站上的某一頁。網址跟著頁面走（頁面改網址不用回來改選單）；label 空白就用頁面標題；
  頁面沒發佈時這個連結不顯示。
- url：自訂網址。站內網址以 / 開頭（英文版會自動加 /en），也可以是 https://… 或 mailto:…。

還沒在後台存過時（例如剛轉檔完），用 default_header／default_footer 依現有頁面產生一份。
"""
import json

from . import db, i18n, queries as Q

HEADER_KEY = "header_menu_json"
FOOTER_KEY = "footer_json"


def _pages(con):
    return {r["id"]: r for r in con.execute("SELECT * FROM pages")}


def default_header(con):
    pages = {r["kind"]: r for r in con.execute("SELECT * FROM pages WHERE kind IN ('performances', 'lyrics', 'articles')")}
    about = con.execute("SELECT * FROM pages WHERE slug = 'about'").fetchone()
    items = []
    perf = pages.get("performances")
    if perf:
        tabs = Q.tab_urls(con)
        items.append({"label": "", "label_en": "", "page_id": perf["id"], "url": "", "children": [
            {"label": "演出列表", "label_en": "Shows", "page_id": perf["id"], "url": ""},
            {"label": "演出統計", "label_en": "Charts", "page_id": None, "url": tabs["charts"]},
            {"label": "歌單統計", "label_en": "Setlists", "page_id": None, "url": tabs["setlist"]},
            {"label": "年度回顧", "label_en": "Replay", "page_id": None, "url": tabs["replay"]},
        ]})
    lyr = pages.get("lyrics")
    if lyr:
        items.append({"label": "", "label_en": "", "page_id": lyr["id"], "url": "", "children": [
            {"label": "歌詞列表", "label_en": "Lyrics", "page_id": lyr["id"], "url": ""},
            {"label": "樂譜", "label_en": "Sheet music", "page_id": None, "url": Q.sheets_url(con)},
        ]})
    for p in (pages.get("articles"), about):
        if p:
            items.append({"label": "", "label_en": "", "page_id": p["id"], "url": "", "children": []})
    return items


def default_footer(con):
    pages = {r["kind"]: r for r in con.execute("SELECT * FROM pages WHERE kind IN ('performances', 'lyrics', 'articles')")}
    about = con.execute("SELECT * FROM pages WHERE slug = 'about'").fetchone()
    email = db.get_setting(con, "contact_email")
    site, site_en = db.get_setting(con, "site_name"), db.get_setting(con, "site_name_en")
    contact = [{"label": email, "label_en": "", "page_id": None, "url": "mailto:" + email}] if email else []
    contact.append({"label": "Instagram @163braces_translate", "label_en": "", "page_id": None,
                    "url": "https://www.instagram.com/163braces_translate/"})
    return {
        "columns": [
            {"title": site, "title_en": site_en, "links": [],
             "text": "收藏台灣歌手 163braces 演出、歌單與歌詞的非官方粉絲網站。",
             "text_en": "An unofficial fan site collecting 163braces' shows, setlists and lyrics."},
            {"title": "網站內容", "title_en": "Explore", "text": "", "text_en": "",
             "links": [{"label": "", "label_en": "", "page_id": p["id"], "url": ""}
                       for p in (pages.get("performances"), pages.get("lyrics"), pages.get("articles"), about) if p]},
            {"title": "聯絡", "title_en": "Contact", "text": "有錯誤、想法或侵權疑慮，歡迎來信。",
             "text_en": "Spotted a mistake or have an idea? Get in touch.", "links": contact},
        ],
        "note": "© %s · 非官方粉絲網站" % site,
        "note_en": "© %s · Unofficial fan site" % site_en,
    }


def add_sheets_link(con):
    """一次性：已經存過的選單（例如轉檔時存的）在「歌詞」底下補上「歌詞列表」「樂譜」。
    只做一次（記在 settings），之後在後台拿掉也不會再加回來；選單裡沒有歌詞頁就不動。"""
    if db.get_setting(con, "nav_sheets_added") == "1":
        return
    lyr = con.execute("SELECT id FROM pages WHERE kind = 'lyrics'").fetchone()
    raw = con.execute("SELECT value FROM settings WHERE key = ?", (HEADER_KEY,)).fetchone()
    if lyr and raw:
        items = json.loads(raw["value"])
        sheets = Q.sheets_url(con)
        for item in items:
            if item.get("page_id") != lyr["id"] or any(c.get("url") == sheets for c in item.get("children") or []):
                continue
            if not item.get("children"):         # 本來沒有下拉：跟演出一樣，第一項是歌詞頁本身
                item["children"] = [{"label": "歌詞列表", "label_en": "Lyrics", "page_id": lyr["id"], "url": ""}]
            item["children"].append({"label": "樂譜", "label_en": "Sheet music", "page_id": None, "url": sheets})
        db.set_setting(con, HEADER_KEY, json.dumps(items, ensure_ascii=False))
    db.set_setting(con, "nav_sheets_added", "1")
    con.commit()


def load_header(con):
    raw = con.execute("SELECT value FROM settings WHERE key = ?", (HEADER_KEY,)).fetchone()
    return json.loads(raw["value"]) if raw else default_header(con)


def load_footer(con):
    raw = con.execute("SELECT value FROM settings WHERE key = ?", (FOOTER_KEY,)).fetchone()
    return json.loads(raw["value"]) if raw else default_footer(con)


def _resolve_link(item, pages, lang, hidden=()):
    label = i18n.tr(lang, item, "label")
    if item.get("page_id"):
        page = pages.get(item["page_id"])
        if not page or not page["published"]:
            return None
        href = Q.page_url(page)
        label = label or i18n.tr(lang, page, "title")
    else:
        href = (item.get("url") or "").strip()
        if href.split("?")[0] in hidden:         # 沒上線的演出頁分頁，跟沒發佈的頁面一樣不出現
            return None
    internal = href.startswith("/")
    return {"label": label,
            "href": i18n.link(lang, href) if internal else href,
            "path": href.split("?")[0] if internal else None,     # 判斷「目前在這一頁」用，不含查詢參數
            "external": bool(href) and not internal and not href.startswith("mailto:")}


def header(con, lang, current_path):
    """頁首選單（已換成目前語言的文字與網址），並標出目前所在的項目。"""
    pages, hidden = _pages(con), Q.hidden_tab_urls(con)
    items = []
    for raw in load_header(con):
        item = _resolve_link(raw, pages, lang, hidden)
        children = [c for c in (_resolve_link(ch, pages, lang, hidden) for ch in raw.get("children") or []) if c]
        if item is None or not (item["href"] or children):
            continue
        item["children"] = children
        items.append(item)
    # 目前所在：網址前綴最長的那一個（首頁只在首頁時算）
    paths = [p for it in items for p in [it["path"]] + [c["path"] for c in it["children"]] if p]
    matches = [p for p in paths if (current_path == p if p == "/" else current_path.startswith(p))]
    active = max(matches, key=len) if matches else None
    for it in items:
        it["on"] = active is not None and (it["path"] == active or any(c["path"] == active for c in it["children"]))
    return items


def footer(con, lang):
    pages, hidden = _pages(con), Q.hidden_tab_urls(con)
    data = load_footer(con)
    columns = []
    for col in data.get("columns") or []:
        columns.append({"title": i18n.tr(lang, col, "title"), "text": i18n.tr(lang, col, "text"),
                        "links": [l for l in (_resolve_link(x, pages, lang, hidden) for x in col.get("links") or []) if l]})
    return {"columns": columns, "note": i18n.tr(lang, data, "note")}


def menu_refs(con):
    """頁首選單與頁尾連到哪些頁面（page_id）與站內網址；後台「頁面與文章」用來標「在選單裡」。"""
    ids, urls = set(), set()
    links = []
    for item in load_header(con):
        links.append(item)
        links += item.get("children") or []
    for col in load_footer(con).get("columns") or []:
        links += col.get("links") or []
    for link in links:
        if link.get("page_id"):
            ids.add(link["page_id"])
        elif (link.get("url") or "").startswith("/"):
            urls.add(link["url"].split("?")[0])
    return ids, urls


def rewrite_urls(con, old, new):
    """頁面改網址時，選單與頁尾裡用自訂網址寫死、在它底下的站內連結（例如 /performances/stats/）一起改。"""
    def fix(link):
        url = link.get("url") or ""
        if url.startswith(old):          # old 結尾是 /，所以 /performances/ 不會誤中 /performances-old/
            link["url"] = new + url[len(old):]

    header_items = load_header(con)
    for item in header_items:
        fix(item)
        for child in item.get("children") or []:
            fix(child)
    footer_data = load_footer(con)
    for col in footer_data.get("columns") or []:
        for link in col.get("links") or []:
            fix(link)
    db.set_setting(con, HEADER_KEY, json.dumps(header_items, ensure_ascii=False))
    db.set_setting(con, FOOTER_KEY, json.dumps(footer_data, ensure_ascii=False))
