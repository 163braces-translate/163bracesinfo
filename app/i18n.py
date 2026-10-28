"""中英雙語。

網址：中文沒有前綴，英文是 /en/ 開頭（跟舊站一樣，舊連結都還能用）。middleware 把 /en 拿掉後
再交給路由，路由本身不用管語言；目前的語言放在 request.state.lang。

資料：每個要翻譯的欄位都有 _en 版本，tr(row, "title") 在英文時取 title_en，空白就退回中文。
介面文字：寫在下面的 T，模板用 t("key")。
"""
import datetime

LANGS = ("zh", "en")

T = {
    "home": ("首頁", "Home"),
    "upcoming": ("即將演出", "Upcoming shows"),
    "upcoming_none": ("目前沒有已公布的演出，有消息會第一時間更新。", "No announced shows yet."),
    "recent_shows": ("最近的演出", "Recent shows"),
    "versions": ("使用這份歌詞的版本", "Versions using these lyrics"),
    "all_performances": ("所有演出", "All performances"),
    "top_songs": ("最近常唱", "Most played lately"),
    "top_songs_hint": ("最近 {n} 場有歌單的演出中，各首歌出現的場數", "Appearances across the last {n} shows with a setlist"),
    "shows": ("場", "shows"),
    "random_listen": ("隨機聆聽", "Random listen"),
    "another_song": ("換一首", "Another song"),
    "full_lyrics": ("完整歌詞", "Full lyrics"),
    "no_lyrics": ("這首還沒有歌詞。", "No lyrics yet."),
    "latest_articles": ("最新文章", "Latest articles"),
    "read_more": ("閱讀更多", "Read more"),
    "date": ("日期", "Date"),
    "event": ("活動名稱", "Event"),
    "type": ("類型", "Type"),
    "venue": ("地點", "Venue"),
    "city": ("城市", "City"),
    "setlist": ("歌單", "Setlist"),
    "songs_n": ("{n} 首", "{n} songs"),
    "order_uncertain": ("此場次曲序不確定", "Running order not confirmed"),
    "no_setlist": ("這場還沒有歌單。", "No setlist for this show yet."),
    "search": ("搜尋", "Search"),
    "search_placeholder": ("活動名稱或地點", "Event or venue"),
    "filters": ("篩選", "Filters"),
    "apply": ("套用", "Apply"),
    "clear": ("清除", "Clear"),
    "all": ("全部", "All"),
    "date_range": ("期間", "Between"),
    "date_before": ("之前", "Before"),
    "date_after": ("之後", "After"),
    "from": ("從", "From"),
    "to": ("到", "To"),
    "sort_desc": ("新到舊", "Newest first"),
    "sort_asc": ("舊到新", "Oldest first"),
    "results": ("共 {n} 場", "{n} shows"),
    "no_results": ("沒有符合條件的演出。", "No shows match these filters."),
    "map": ("地圖", "Map"),
    "map_hint": ("點縣市篩選，再點一次取消", "Tap a city to filter, tap again to clear"),
    "overseas": ("海外與其他", "Overseas & other"),
    "soon": ("即將到來", "Upcoming"),
    "close": ("關閉", "Close"),
    "tab_list": ("演出列表", "Shows"),
    "tab_charts": ("演出統計", "Charts"),
    "tab_setlist": ("歌單統計", "Setlists"),
    "tab_replay": ("年度回顧", "Replay"),
    "year": ("年份", "Year"),
    "all_time": ("全部時間", "All time"),
    "total_shows": ("演出場次", "Shows"),
    "chart_history": ("歷史演出統計", "Shows per month, all time"),
    "chart_cumulative": ("各類型累積演出場次", "Cumulative shows by type"),
    "chart_monthly": ("各類型月度演出", "Shows per month by type"),
    "chart_city": ("城市演出比例", "Shows by city"),
    "chart_weekday": ("各類型星期分布", "Shows per weekday by type"),
    "chart_weekday_pie": ("星期演出比例", "Shows by weekday"),
    "setlist_progress": ("歌單收集進度", "Setlist collection progress"),
    "setlist_progress_text": ("已發生的 {total} 場演出中，{done} 場有歌單，還缺 {missing} 場。",
                              "{done} of {total} past shows have a setlist; {missing} still missing."),
    "donation_call": ("每補齊一份缺漏的歌單，我們就捐出新台幣 {amount} 元。歡迎提供！",
                      "For every missing setlist filled in, we donate NT${amount}. Contributions welcome!"),
    "chart_song_cumulative": ("各歌曲累積演出次數", "Cumulative plays per song"),
    "show_top": ("前 {n} 名", "Top {n}"),
    "show_all": ("全部", "All"),
    "setlist_length": ("各類型每場曲目數", "Songs per show by type"),
    "setlist_length_hint": ("不含曲目數少於 {n} 首的場次（多半是短暫嘉賓之類的特例）。",
                            "Shows with fewer than {n} songs are left out (usually brief guest spots)."),
    "min": ("最少", "Min"),
    "mean": ("平均", "Mean"),
    "median": ("中位數", "Median"),
    "max": ("最多", "Max"),
    "ties": ("另有 {n} 場並列", "{n} more tied"),
    "lyrics": ("歌詞", "Lyrics"),
    "other_lyrics": ("其他歌詞", "Other lyrics"),
    "expand_all": ("全部展開", "Expand all"),
    "collapse_all": ("全部收起", "Collapse all"),
    "view_both": ("中英對照", "Both"),
    "view_left": ("只看中文", "Chinese only"),
    "view_right": ("只看英文", "English only"),
    "composer": ("作曲", "Music"),
    "lyricist": ("作詞", "Lyrics"),
    "artist": ("演唱", "Artist"),
    "videos": ("影片", "Videos"),
    "album": ("專輯", "Album"),
    "played_n": ("現場唱過 {n} 次", "Played live {n} times"),
    "last_played": ("最近一次：{date}", "Last played: {date}"),
    "articles": ("文章", "Articles"),
    "not_found": ("找不到這一頁", "Page not found"),
    "not_found_text": ("這個網址可能打錯了，或是頁面已經搬家。", "This page may have moved or never existed."),
    "back_home": ("回首頁", "Back to home"),
    "contact": ("聯絡", "Contact"),
    "unofficial": ("非官方粉絲網站", "Unofficial fan site"),
    "menu": ("選單", "Menu"),
    "lang_switch": ("English", "中文"),
}

WEEKDAYS = {
    "zh": ["一", "二", "三", "四", "五", "六", "日"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def t(lang, key, **kw):
    pair = T.get(key)
    if not pair:
        return key
    text = pair[1] if lang == "en" else pair[0]
    return text.format(**kw) if kw else text


def tr(lang, row, field):
    """欄位的當前語言版本；英文空白時退回中文。"""
    if row is None:
        return ""
    if lang == "en":
        try:
            value = row[field + "_en"]
        except (KeyError, IndexError):
            value = None
        if value:
            return value
    try:
        return row[field] or ""
    except (KeyError, IndexError):
        return ""


def link(lang, path):
    """站內網址加上語言前綴。path 開頭要有斜線。"""
    if lang == "en" and not path.startswith(("/static/", "/media/", "/images/", "/admin")):
        return "/en" + path
    return path


def weekday(lang, iso_date):
    d = datetime.date.fromisoformat(iso_date)
    return WEEKDAYS[lang][d.weekday()]


def month_label(lang, month):
    return MONTHS_EN[month - 1] if lang == "en" else "%d月" % month


def weekday_labels(lang):
    return WEEKDAYS[lang] if lang == "en" else ["週" + d for d in WEEKDAYS["zh"]]


def ym_label(lang, ym):
    """"2026-10" → 「2026 年 10 月」／"Oct 2026"。"""
    year, month = int(ym[:4]), int(ym[5:7])
    return "%s %d" % (MONTHS_EN[month - 1], year) if lang == "en" else "%d 年 %d 月" % (year, month)
