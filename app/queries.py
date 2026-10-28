"""前台頁面用到的查詢。只讀；寫入都在 admin.py。

日期一律以台灣時間的「今天」為準：今天的演出算「即將演出」，也算「已發生」（歌單進度要算進去）。
"""
import datetime
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from . import db
from .i18n import month_label, tr, weekday_labels

TZ = ZoneInfo("Asia/Taipei")

# 圖表配色：八個色相，順序固定（相鄰兩色在色盲模擬下也分得開，取自 dataviz 的驗證過的預設色盤）。
# 不循環使用：超過八個系列時，多出來的併成灰色的「其他」，不再生新顏色。
CHART_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER_COLOR = "#b4b9c2"

# 曲目數少於這個數字的場次不列入「每場曲目數」：一兩首的場次多半是短暫嘉賓，
# 跟一般演出不是同一回事，放進來會把每個數字都往下拉。
SETLIST_STATS_MIN_SONGS = 3


def today():
    return datetime.datetime.now(TZ).date().isoformat()


def color(i):
    return CHART_COLORS[i] if i < len(CHART_COLORS) else OTHER_COLOR


# ==================================================================== 圖片、影片
def youtube_id(url):
    m = re.search(r"(?:youtu\.be/|v=|/embed/|/shorts/|/live/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def image_url(image_id, width=600):
    return "/images/%d/w%d/" % (image_id, width) if image_id else ""


def song_cover_id(song):
    return song["cover_image_id"] or song["album_cover_id"]


# ==================================================================== 頁面
def pages_by_kind(con):
    return {r["kind"]: r for r in con.execute(
        "SELECT * FROM pages WHERE kind IN ('home', 'performances', 'lyrics', 'articles')")}


def page_url(page):
    return "/%s/" % page["slug"] if page["slug"] else "/"


# 演出頁的四個分頁各有自己的網址，沿用舊站：/performances/、/performances/stats/、/performances/setlist/、/replay/。
# 統計、歌單掛在演出頁底下（演出頁改網址會一起變）；年度回顧舊站就在最上層，固定是 /replay/。
TAB_SUBPATHS = {"charts": "stats", "setlist": "setlist"}
REPLAY_PATH = "/replay/"


def tab_urls(con):
    row = con.execute("SELECT slug FROM pages WHERE kind = 'performances'").fetchone()
    base = "/%s/" % row["slug"] if row else "/performances/"
    urls = {"list": base}
    urls.update({tab: base + sub + "/" for tab, sub in TAB_SUBPATHS.items()})
    urls["replay"] = REPLAY_PATH
    return urls


def tab_statuses(con):
    """演出頁各分頁的狀態。「演出列表」就是演出頁本身；另外三個沒有自己的頁面，狀態存在設定裡。"""
    perf = con.execute("SELECT status FROM pages WHERE kind = 'performances'").fetchone()
    out = {"list": perf["status"] if perf else "live"}
    for tab in TAB_TITLES_KEYS:
        out[tab] = db.get_setting(con, "tab_status_" + tab) or "live"
    return out


def hidden_tab_urls(con):
    """訪客看不到的分頁網址：分頁本身沒上線，或演出頁沒上線（分頁都在演出頁底下）。選單、sitemap 用。"""
    status, urls = tab_statuses(con), tab_urls(con)
    return {urls[t] for t in TAB_TITLES_KEYS if status[t] != "live" or status["list"] != "live"}


TAB_TITLES_KEYS = ("charts", "setlist", "replay")      # 有自己狀態的分頁（演出列表跟著演出頁）


def lyrics_prefix(con):
    row = con.execute("SELECT slug FROM pages WHERE kind = 'lyrics'").fetchone()
    return "/%s/" % row["slug"] if row else "/lyrics/"


def articles_under(con, slug, limit=-1):
    """某一頁（通常是「文章」列表頁）底下、所有層的已發佈文章，新到舊。跟舊站一樣，文章列表只列自己底下的文章。"""
    return con.execute("SELECT * FROM pages WHERE kind = 'article' AND published = 1 AND slug LIKE ? "
                       "ORDER BY published_at DESC, id DESC LIMIT ?", (slug + "/%", limit)).fetchall()


def latest_articles(con, n=3):
    row = con.execute("SELECT slug FROM pages WHERE kind = 'articles'").fetchone()
    return articles_under(con, row["slug"], n) if row else []


def child_pages(con, page_id):
    """直接掛在這一頁底下、已發佈的頁面（不含文章：文章由文章列表頁負責列）。"""
    return con.execute("SELECT * FROM pages WHERE parent_id = ? AND published = 1 AND kind != 'article' "
                       "ORDER BY sort_order, id", (page_id,)).fetchall()


# ==================================================================== 演出
PERF_SELECT = """
    SELECT p.*, t.name AS type_name, t.name_en AS type_name_en, t.sort_order AS type_order,
           c.name AS city_name, c.name_en AS city_name_en, c.map_key, c.sort_order AS city_order,
           (SELECT COUNT(*) FROM setlist_items s WHERE s.performance_id = p.id) AS song_count
    FROM performances p
    JOIN event_types t ON t.id = p.event_type_id
    JOIN cities c ON c.id = p.city_id
"""


def upcoming(con, n):
    return con.execute(PERF_SELECT + " WHERE p.event_date >= ? ORDER BY p.event_date, p.id LIMIT ?",
                       (today(), n)).fetchall()


def recent(con, n):
    return con.execute(PERF_SELECT + " WHERE p.event_date < ? ORDER BY p.event_date DESC, p.id DESC LIMIT ?",
                       (today(), n)).fetchall()


def parse_filters(params):
    """網址參數 → 篩選條件。參數名稱沿用舊站，舊的分享連結照樣有效。"""
    def ids(key):
        return [int(v) for v in params.getlist(key) if str(v).isdigit()]

    mode = params.get("date_filter_type") or "range"
    return {
        "q": (params.get("q") or "").strip(),
        "city": ids("city"),
        "event_type": ids("event_type"),
        "date_filter_type": mode if mode in ("range", "before", "after") else "range",
        "date_from": params.get("date_from") or "",
        "date_to": params.get("date_to") or "",
        "sort": "event_date_asc" if params.get("sort") == "event_date_asc" else "event_date_desc",
    }


def _where(f, skip_city=False):
    where, args = [], []
    if f["q"]:
        like = "%" + f["q"] + "%"
        where.append("(p.event_name LIKE ? OR p.event_name_en LIKE ? OR p.venue LIKE ? OR p.venue_en LIKE ?)")
        args += [like] * 4
    if f["city"] and not skip_city:
        where.append("p.city_id IN (%s)" % ",".join("?" * len(f["city"])))
        args += f["city"]
    if f["event_type"]:
        where.append("p.event_type_id IN (%s)" % ",".join("?" * len(f["event_type"])))
        args += f["event_type"]
    mode, d_from, d_to = f["date_filter_type"], f["date_from"], f["date_to"]
    if mode == "before" and d_to:
        where.append("p.event_date <= ?"); args.append(d_to)
    elif mode == "after" and d_from:
        where.append("p.event_date >= ?"); args.append(d_from)
    elif mode == "range":
        if d_from:
            where.append("p.event_date >= ?"); args.append(d_from)
        if d_to:
            where.append("p.event_date <= ?"); args.append(d_to)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def performances(con, f):
    where, args = _where(f)
    order = "p.event_date, p.id" if f["sort"] == "event_date_asc" else "p.event_date DESC, p.id DESC"
    rows = [dict(r) for r in con.execute(PERF_SELECT + where + " ORDER BY " + order, args)]
    sets = setlists(con, [r["id"] for r in rows if r["song_count"]])
    for r in rows:
        r["setlist"] = sets.get(r["id"], [])
    return rows


def setlists(con, perf_ids):
    """演出 id → 歌單（每首附上歌詞頁 slug，有歌詞的可以直接點過去）。"""
    out = defaultdict(list)
    for i in range(0, len(perf_ids), 500):
        chunk = perf_ids[i:i + 500]
        for r in con.execute("""
                SELECT s.performance_id, s.position, s.custom_title, s.note,
                       g.id AS song_id, g.title, g.title_en, g.artist, g.artist_en, l.slug AS lyrics_slug
                FROM setlist_items s
                LEFT JOIN songs g ON g.id = s.song_id
                LEFT JOIN lyrics l ON l.id = g.lyrics_id AND l.published = 1
                WHERE s.performance_id IN (%s) ORDER BY s.performance_id, s.position, s.id"""
                             % ",".join("?" * len(chunk)), chunk):
            out[r["performance_id"]].append(dict(r))
    return out


def city_counts(con, f):
    """地圖用：套用除了城市以外的篩選後，各城市的場次。"""
    where, args = _where(f, skip_city=True)
    return {r["city_id"]: r["n"] for r in con.execute(
        "SELECT p.city_id, COUNT(*) AS n FROM performances p" + where + " GROUP BY p.city_id", args)}


def cities(con):
    return con.execute("SELECT * FROM cities ORDER BY sort_order, name").fetchall()


def event_types(con):
    return con.execute("SELECT * FROM event_types ORDER BY sort_order, name").fetchall()


# ==================================================================== 曲庫、歌詞
SONG_SELECT = """
    SELECT g.*, a.name AS album_name, a.name_en AS album_name_en, a.cover_image_id AS album_cover_id,
           l.slug AS lyrics_slug, l.published AS lyrics_published
    FROM songs g JOIN albums a ON a.id = g.album_id
    LEFT JOIN lyrics l ON l.id = g.lyrics_id
"""


def song_title(lang, row):
    """歌單一行的顯示名稱：曲庫歌曲用曲名，自訂曲名照填的。"""
    if row["song_id"] is None:
        return row["custom_title"]
    return tr(lang, row, "title")


def top_songs(con, lang, n, window):
    """最近 window 場有歌單的（已發生）演出中，出現場數最多的 n 首。"""
    perf_ids = [r["id"] for r in con.execute(
        "SELECT p.id FROM performances p WHERE p.event_date <= ? "
        "AND EXISTS (SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id) "
        "ORDER BY p.event_date DESC LIMIT ?", (today(), window))]
    if not perf_ids:
        return [], 0
    counter, info = Counter(), {}
    for pid, items in setlists(con, perf_ids).items():
        seen = set()
        for it in items:
            key = ("s", it["song_id"]) if it["song_id"] else ("c", it["custom_title"])
            if key in seen:
                continue          # 同一場唱兩次只算一場
            seen.add(key)
            counter[key] += 1
            info[key] = it
    top = []
    for key, count in counter.most_common(n):
        it = info[key]
        top.append({"title": song_title(lang, it), "count": count, "lyrics_slug": it["lyrics_slug"],
                    "artist": tr(lang, it, "artist") if it["song_id"] else ""})
    return top, len(perf_ids)


def random_song(con, exclude=None, song_id=None):
    """首頁隨機聆聽：有影片、而且有已發佈歌詞的歌。"""
    rows = con.execute(SONG_SELECT + " WHERE g.listen_url != '' AND l.published = 1").fetchall()
    if song_id:
        rows = [r for r in rows if r["id"] == song_id] or rows
    elif exclude and len(rows) > 1:
        rows = [r for r in rows if r["id"] != exclude]
    if not rows:
        return None
    song = dict(random.choice(rows))
    lyr = con.execute("SELECT * FROM lyrics WHERE id = ?", (song["lyrics_id"],)).fetchone()
    song["lyrics"] = lyr
    song["blocks"] = main_part(json.loads(lyr["sections_json"]))
    return song


def song_play_stats(con, song_ids):
    """這些歌（同一份歌詞的各版本）現場唱過幾次、最近一次是哪天。"""
    if not song_ids:
        return 0, None
    q = ",".join("?" * len(song_ids))
    row = con.execute("SELECT COUNT(*) AS n, MAX(p.event_date) AS last FROM setlist_items s "
                      "JOIN performances p ON p.id = s.performance_id "
                      "WHERE s.song_id IN (%s) AND p.event_date <= ?" % q, list(song_ids) + [today()]).fetchone()
    return row["n"], row["last"]


def split_parts(blocks):
    """sections_json → [(方框標題, 方框英文標題, [區塊…])]。第一個方框是主歌詞，標題空白。"""
    parts = [("", "", [])]
    for b in blocks:
        if b.get("type") == "part":
            parts.append((b.get("title") or "", b.get("title_en") or "", []))
        else:
            parts[-1][2].append(b)
    return [p for i, p in enumerate(parts) if i == 0 or p[2] or p[0]]


def main_part(blocks):
    return split_parts(blocks)[0][2]


def albums_with_songs(con):
    """每張專輯（照排序，含沒有歌的）與它的曲目。"""
    albums = [dict(a) for a in con.execute("SELECT * FROM albums ORDER BY sort_order, id")]
    by_album = defaultdict(list)
    for s in con.execute(SONG_SELECT + " ORDER BY g.sort_order, g.id"):
        by_album[s["album_id"]].append(s)
    for a in albums:
        a["songs"] = by_album.get(a["id"], [])
    return albums


def other_lyrics_position(con, album_count):
    """「其他歌詞」方框排在第幾張專輯後面（0＝最前面）；沒設定過就放最後。"""
    value = db.get_setting(con, "lyrics_other_position")
    return min(int(value), album_count) if str(value).isdigit() else album_count


def lyrics_boxes(con):
    """歌詞索引的方框，照後台「歌詞索引排序」排好：每張有歌的專輯一個，
    「其他歌詞」（沒對應到歌曲的歌詞）插在設定的位置。"""
    albums = albums_with_songs(con)
    boxes = [{"kind": "album", "album": a} for a in albums]
    orphans = orphan_lyrics(con)
    if orphans:
        boxes.insert(other_lyrics_position(con, len(albums)), {"kind": "other", "lyrics": orphans})
    return [b for b in boxes if b["kind"] == "other" or b["album"]["songs"]]


def orphan_lyrics(con):
    """沒有任何歌曲指向的已發佈歌詞（歌詞索引的「其他」方框）。"""
    return con.execute("SELECT * FROM lyrics WHERE published = 1 AND id NOT IN "
                       "(SELECT lyrics_id FROM songs WHERE lyrics_id IS NOT NULL) "
                       "ORDER BY sort_order, id").fetchall()


# ==================================================================== 統計分頁
def stats_charts(con, lang, year):
    """演出統計分頁的六張圖。year 是整數或 "all"；上面兩張涵蓋全部歷史，不受年份影響。"""
    types = event_types(con)
    names = [tr(lang, t, "name") for t in types]
    if year == "all":
        where, args = "", []
    else:
        where, args = " WHERE substr(p.event_date, 1, 4) = ?", [str(year)]

    def by_type(dataset_rows, labels, key_index):
        matrix = {t["id"]: [0] * len(labels) for t in types}
        for r in dataset_rows:
            if r["event_type_id"] in matrix:
                matrix[r["event_type_id"]][key_index(r)] = r["n"]
        return {"labels": labels, "datasets": [
            {"label": names[i], "data": matrix[t["id"]], "backgroundColor": color(i), "borderColor": color(i)}
            for i, t in enumerate(types)]}

    monthly = by_type(
        con.execute("SELECT p.event_type_id, CAST(substr(p.event_date, 6, 2) AS INTEGER) AS m, COUNT(*) AS n "
                    "FROM performances p" + where + " GROUP BY 1, 2", args).fetchall(),
        [month_label(lang, m) for m in range(1, 13)], lambda r: r["m"] - 1)

    # strftime('%w')：0＝週日。換成週一＝0 … 週日＝6
    weekday = by_type(
        con.execute("SELECT p.event_type_id, (CAST(strftime('%w', p.event_date) AS INTEGER) + 6) % 7 AS d, "
                    "COUNT(*) AS n FROM performances p" + where + " GROUP BY 1, 2", args).fetchall(),
        weekday_labels(lang), lambda r: r["d"])
    # 顏色跟著星期走（週一永遠同一色），不跟著名次走，換年份時顏色才不會亂跳
    totals = [(label, sum(ds["data"][i] for ds in weekday["datasets"]), i) for i, label in enumerate(weekday["labels"])]
    totals = sorted([x for x in totals if x[1]], key=lambda x: -x[1])     # 沒有演出的星期不畫，零面積扇形只會擠圖例
    weekday_pie = {"labels": [x[0] for x in totals],
                   "datasets": [{"data": [x[1] for x in totals], "backgroundColor": [color(x[2]) for x in totals]}]}

    city_rows = con.execute("SELECT c.name, c.name_en, COUNT(*) AS n FROM performances p JOIN cities c ON c.id = p.city_id"
                            + where + " GROUP BY c.id ORDER BY n DESC", args).fetchall()
    slices = [(tr(lang, r, "name"), r["n"]) for r in city_rows]
    if len(slices) > len(CHART_COLORS):      # 顏色只有八個：前七名各一色，其餘併成「其他」
        keep = len(CHART_COLORS) - 1
        slices = slices[:keep] + [("Other" if lang == "en" else "其他", sum(n for _, n in slices[keep:]))]
    folded = len(city_rows) > len(slices)
    city_pie = {"labels": [s[0] for s in slices],
                "datasets": [{"data": [s[1] for s in slices],
                              "backgroundColor": [OTHER_COLOR if folded and i == len(slices) - 1 else color(i)
                                                  for i in range(len(slices))]}]}

    hist_rows = con.execute("SELECT p.event_type_id, substr(p.event_date, 1, 7) AS ym, COUNT(*) AS n "
                            "FROM performances p GROUP BY 1, 2").fetchall()
    months = sorted({r["ym"] for r in hist_rows})
    history = by_type(hist_rows, months, lambda r: months.index(r["ym"]))

    cumulative = {"labels": months, "datasets": []}
    for ds in history["datasets"]:
        running, series = 0, []
        for v in ds["data"]:
            running += v
            series.append(running)
        if running:
            cumulative["datasets"].append({"label": ds["label"], "data": series, "borderColor": ds["borderColor"],
                                           "backgroundColor": ds["borderColor"], "borderWidth": 2,
                                           "cubicInterpolationMode": "monotone", "pointRadius": 0})
    total = con.execute("SELECT COUNT(*) FROM performances p" + where, args).fetchone()[0]
    # 最下面的地圖：這一年（或全部）各城市的場次
    city_counts = {r["city_id"]: r["n"] for r in con.execute(
        "SELECT p.city_id, COUNT(*) AS n FROM performances p" + where + " GROUP BY p.city_id", args)}
    return {"monthly": monthly, "weekday": weekday, "weekday_pie": weekday_pie, "city_pie": city_pie,
            "history": history, "cumulative": cumulative, "total": total, "city_counts": city_counts}


def available_years(con):
    return [r[0] for r in con.execute(
        "SELECT DISTINCT substr(event_date, 1, 4) FROM performances ORDER BY 1 DESC")]


def setlist_progress(con):
    row = con.execute(
        "SELECT COUNT(*) AS total, SUM(EXISTS (SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id)) AS done "
        "FROM performances p WHERE p.event_date <= ?", (today(),)).fetchone()
    total, done = row["total"] or 0, row["done"] or 0
    return {"total": total, "done": done, "missing": total - done,
            "percent": round(done / total * 100, 1) if total else 0}


def song_cumulative(con, lang, top_n):
    rows = con.execute("""
        SELECT substr(p.event_date, 1, 7) AS ym, s.song_id, s.custom_title, g.title, g.title_en, COUNT(*) AS n
        FROM setlist_items s JOIN performances p ON p.id = s.performance_id
        LEFT JOIN songs g ON g.id = s.song_id
        WHERE p.event_date <= ? GROUP BY 1, 2, 3""", (today(),)).fetchall()
    months = sorted({r["ym"] for r in rows})
    by_song, totals = defaultdict(dict), Counter()
    for r in rows:
        label = song_title(lang, r)
        by_song[label][r["ym"]] = by_song[label].get(r["ym"], 0) + r["n"]
        totals[label] += r["n"]
    ranked = [name for name, _ in totals.most_common()]

    def build(names):
        datasets = []
        for i, name in enumerate(names):
            running, series = 0, []
            for m in months:
                running += by_song[name].get(m, 0)
                series.append(running)
            # 前八名各一色；之後的歌用灰色細線（滑鼠移上去仍看得到曲名）
            datasets.append({"label": name, "data": series, "borderColor": color(i), "backgroundColor": color(i),
                             "borderWidth": 2 if i < len(CHART_COLORS) else 1,
                             "cubicInterpolationMode": "monotone", "pointRadius": 0})
        return {"labels": months, "datasets": datasets}
    return build(ranked), build(ranked[:top_n])


def song_probability(con, lang):
    """歌單統計的「演出機率對照表」：曲庫裡的歌（不含自訂曲名）在有歌單的已發生演出中出現在幾場。
    回傳曲庫的歌與每一場（新到舊）唱了哪幾首（歌的索引，同一場唱兩次只算一次）；近 N 場在瀏覽器端算。"""
    songs = con.execute(SONG_SELECT + " ORDER BY a.sort_order, g.sort_order, g.id").fetchall()
    index = {s["id"]: i for i, s in enumerate(songs)}
    prefix = lyrics_prefix(con)
    perf_ids = [r["id"] for r in con.execute(
        "SELECT p.id FROM performances p WHERE p.event_date <= ? "
        "AND EXISTS (SELECT 1 FROM setlist_items s WHERE s.performance_id = p.id) "
        "ORDER BY p.event_date DESC, p.id DESC", (today(),))]
    by_perf = defaultdict(set)
    for r in con.execute("SELECT performance_id, song_id FROM setlist_items WHERE song_id IS NOT NULL"):
        if r["song_id"] in index:
            by_perf[r["performance_id"]].add(index[r["song_id"]])
    return {
        "songs": [{"title": tr(lang, s, "title"),
                   "url": prefix + s["lyrics_slug"] + "/" if s["lyrics_slug"] and s["lyrics_published"] else ""}
                  for s in songs],
        "shows": [sorted(by_perf[pid]) for pid in perf_ids],
    }


def setlist_length_stats(con):
    rows = [dict(r) for r in con.execute(PERF_SELECT + " WHERE p.event_date <= ?", (today(),))
            if r["song_count"] >= SETLIST_STATS_MIN_SONGS]
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["event_type_id"]].append(r)
    out = []
    for t in event_types(con):
        perfs = grouped.get(t["id"])
        if not perfs:
            continue
        counts = [p["song_count"] for p in perfs]
        lo, hi = min(counts), max(counts)

        def latest_with(c):    # 並列時取最新的一場
            return max((p for p in perfs if p["song_count"] == c), key=lambda p: p["event_date"])
        out.append({"type": t, "count": len(counts), "min": lo, "max": hi,
                    "mean": round(statistics.mean(counts), 1), "median": round(statistics.median(counts), 1),
                    "min_perf": latest_with(lo), "max_perf": latest_with(hi),
                    "min_ties": counts.count(lo) - 1, "max_ties": counts.count(hi) - 1})
    return out


def replay_data(con, year):
    songs = con.execute(SONG_SELECT + " ORDER BY g.sort_order, g.title").fetchall()
    perfs = con.execute(PERF_SELECT + " WHERE substr(p.event_date, 1, 4) = ? ORDER BY p.event_date",
                        (str(year),)).fetchall()
    types = {t["name"]: {"order": t["sort_order"], "name_en": t["name_en"] or t["name"]} for t in event_types(con)}
    cities_ = {c["name"]: {"order": c["sort_order"], "name_en": c["name_en"] or c["name"]} for c in cities(con)}
    logo = db.get_setting(con, "replay_logo_id")
    return {"songs": songs, "performances": perfs, "event_types": types, "cities": cities_,
            "logo_url": image_url(int(logo), 400) if str(logo).isdigit() else ""}
