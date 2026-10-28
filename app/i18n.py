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
    "top_songs_hint": ("最近 {n} 場有歌單的演出中，各首歌出現的比例", "Share of the last {n} shows with a setlist that featured each song"),
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
    "view_both": ("雙語對照", "Side by side"),
    "view_left": ("中文", "Chinese"),
    "view_right": ("English", "English"),
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
    # ---- 粉絲功能
    "login": ("登入", "Sign in"),
    "logout": ("登出", "Sign out"),
    "my_page": ("我的", "My page"),
    "login_with_google": ("用 Google 帳號登入", "Sign in with Google"),
    "login_intro": ("登入後可以記錄去過的場次、收藏喜歡的歌、在首頁跑馬燈留言，以及補充演出資訊與投稿樂譜。",
                    "Sign in to track the shows you attended, like songs, post on the home page ticker, and contribute show details and sheet music."),
    "login_privacy": ("登入代表你同意我們的隱私權政策：只會取得你的 Google 名字、email 與大頭貼。",
                      "By signing in you agree to our privacy policy: we only receive your Google name, email and profile picture."),
    "login_unavailable": ("登入功能還沒開放。", "Sign-in is not available yet."),
    "dev_login": ("測試登入（只在本機開發時出現）", "Test sign-in (local development only)"),
    "need_login_to": ("登入後才能使用這個功能", "Sign in to use this"),
    "privacy": ("隱私權政策", "Privacy policy"),
    "attended": ("我去過", "I was there"),
    "attended_on": ("✓ 我去過", "✓ I was there"),
    "fans_attended": ("{n} 位粉絲去過", "{n} fans were there"),
    "suggest_edit": ("補充資訊", "Suggest an edit"),
    "add_setlist": ("＋補歌單", "+ Setlist"),
    "like": ("喜歡", "Like"),
    "likes_n": ("{n} 人喜歡", "{n} likes"),
    "anonymous": ("匿名", "Anonymous"),
    "fan": ("粉絲", "Fan"),
    "saved": ("已儲存", "Saved"),
    "save": ("儲存", "Save"),
    "banned": ("你的帳號已被停止投稿。", "Your account can no longer post."),
    "daily_limit": ("每 24 小時最多投稿 {n} 次，晚點再來吧。", "You can post up to {n} times per 24 hours. Try again later."),
    "marquee": ("粉絲留言", "Fan messages"),
    "marquee_post": ("我也要說", "Say something"),
    "marquee_placeholder": ("想對 163braces 說的話（最多 {n} 個中文字或英文單字）",
                            "Your message to 163braces (up to {n} words)"),
    "marquee_empty": ("請輸入留言。", "Please write something."),
    "marquee_too_long": ("最多 {n} 個中文字或英文單字。", "Up to {n} words."),
    "marquee_sent": ("已送出！", "Posted!"),
    "units_left": ("還可以輸入 {n} 個字", "{n} words left"),
    "units_over": ("超過 {n} 個字", "{n} words over"),
    "sign_as": ("署名", "Sign as"),
    "name_google": ("Google 帳號名", "Google name"),
    "name_nickname": ("我的暱稱", "My nickname"),
    "name_anonymous": ("匿名", "Anonymous"),
    "send": ("送出", "Send"),
    "cancel": ("取消", "Cancel"),
    "tab_footprint": ("我的足跡", "My shows"),
    "tab_likes": ("喜歡的歌", "Liked songs"),
    "tab_submissions": ("我的投稿", "My submissions"),
    "tab_settings": ("設定", "Settings"),
    "fp_total": ("去過的場次", "Shows attended"),
    "fp_songs": ("現場聽過的歌", "Songs heard live"),
    "fp_first": ("第一次", "First show"),
    "fp_by_year": ("每年去了幾場", "Shows per year"),
    "fp_by_type": ("演出類型", "Show types"),
    "fp_map": ("去過的縣市", "Where you went"),
    "fp_heard": ("現場聽過最多次的歌", "Most heard live"),
    "fp_never": ("還沒在現場聽過", "Not heard live yet"),
    "fp_list": ("去過的場次", "Shows"),
    "fp_empty": ("還沒有紀錄。到演出頁按「我去過」開始記錄吧！", "Nothing yet. Mark shows as attended on the performances page!"),
    "times": ("次", "×"),
    "likes_empty": ("還沒有喜歡的歌。在歌詞頁按 ♥ 收藏。", "No liked songs yet. Tap ♥ on a lyrics page."),
    "status_pending": ("審核中", "Pending"),
    "status_approved": ("已採用", "Approved"),
    "status_rejected": ("未採用", "Not accepted"),
    "status_removed": ("已下架", "Removed"),
    "status_visible": ("顯示中", "Visible"),
    "status_hidden": ("已隱藏", "Hidden"),
    "subs_empty": ("還沒有投稿。", "No submissions yet."),
    "nickname": ("暱稱", "Nickname"),
    "nickname_help": ("投稿時選「我的暱稱」就會顯示這個名字。", "Shown when you sign a post with your nickname."),
    "handle": ("個人頁網址", "Profile URL"),
    "profile_public": ("公開我的個人頁（去過的場次與喜歡的歌）", "Make my profile public (shows and liked songs)"),
    "delete_account": ("刪除帳號", "Delete account"),
    "delete_help": ("所有紀錄與投稿會一起刪除，無法復原。請在下面輸入 DELETE 確認。",
                    "All your records and submissions will be deleted. Type DELETE to confirm."),
    "contribute_title": ("補充演出資訊", "Suggest an edit"),
    "contribute_intro": ("看到錯誤或缺少的歌單嗎？直接在下面修改，送出後由管理者確認再更新。",
                         "Spotted a mistake or a missing setlist? Edit below; an admin will review it before it goes live."),
    "contribute_setlist_help": ("一行一首；備註用「｜」接在後面，例如：愛情限時批｜Cover",
                                "One song per line; add a note after \"｜\", e.g. Song｜Cover"),
    "contribute_source": ("資料來源（必填）", "Source (required)"),
    "contribute_source_help": ("例如：官方 IG 貼文連結、自己在現場、朋友提供", "e.g. an official post, you were there, a friend"),
    "contribute_message": ("想對管理者說的話（選填）", "Note to the admin (optional)"),
    "contribute_nothing": ("你沒有修改任何內容。", "You didn't change anything."),
    "contribute_need_source": ("請填寫資料來源。", "Please give a source."),
    "contribute_thanks": ("謝謝你的補充！管理者確認後就會更新。", "Thanks! An admin will review your edit."),
    "sheets": ("樂譜", "Sheet music"),
    "sheets_notice": ("粉絲採譜，非官方版本。權利人如需下架請來信 {email}。",
                      "Fan transcriptions, not official. Rights holders may request removal at {email}."),
    "sheet_submit": ("投稿樂譜", "Submit sheet music"),
    "sheet_by": ("{name} 採譜", "Transcribed by {name}"),
    "sheet_title": ("樂譜名稱", "Title"),
    "sheet_title_help": ("例如：吉他和弦譜、鋼琴伴奏、簡譜", "e.g. Guitar chords, Piano accompaniment"),
    "sheet_files": ("樂譜圖檔（JPG、PNG，每張 10MB 以內，最多 {n} 張）", "Images (JPG/PNG, up to 10MB each, max {n})"),
    "sheet_text": ("或貼上文字譜", "Or paste a text version"),
    "sheet_video": ("演奏影片連結（強烈建議附上）", "Performance video link (strongly recommended)"),
    "sheet_video_help": ("附上你照這份譜演奏的影片，其他人比較容易確認正確性。", "A video of you playing it helps others trust the transcription."),
    "sheet_own": ("這是我自己採的譜，不是翻拍或轉貼官方出版的樂譜", "I transcribed this myself; it is not a copy of official sheet music"),
    "sheet_need_own": ("請確認這是你自己採的譜。", "Please confirm you transcribed this yourself."),
    "sheet_need_title": ("請填樂譜名稱。", "Please give a title."),
    "sheet_need_content": ("請上傳圖檔或貼上文字譜。", "Please upload images or paste text."),
    "sheet_too_many": ("圖檔最多 {n} 張。", "Up to {n} images."),
    "sheet_bad_video": ("影片連結要是 https:// 開頭的網址。", "The video link must be a web address."),
    "sheet_file_too_large": ("有圖檔超過 10MB。", "An image is larger than 10MB."),
    "sheet_bad_file": ("有檔案不是 JPG、PNG 或 WebP 圖片。", "A file is not a JPG, PNG or WebP image."),
    "sheet_thanks": ("謝謝你的樂譜！管理者確認後就會公開。", "Thanks! Your sheet music will appear after review."),
    "public_profile": ("{name} 的個人頁", "{name}'s profile"),
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
