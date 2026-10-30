"""演出頁行事曆的放假日（紅字）。

資料來源以行政院人事行政總處公告的「中華民國政府行政機關辦公日曆表」為準：
從政府資料開放平台（data.gov.tw 資料集 14718）列出各年度的 CSV，下載整年每一天放不放假。
官方抓不到時才改抓 GitHub 上 ruyut/TaiwanCalendar 整理好的同一份資料（透過 jsDelivr），
它不保證一直有人維護，所以只當備用。都抓不到的話，後台也可以直接上傳官方 CSV。

每年的資料存在 calendar_days（一天一列：放不放假、說明）；calendar_years 記這一年從哪裡來。
前台只拿「跟一般週末規則不一樣」或「有名稱」的日子（國定假日、補假、補行上班）。

正式站上每天看一次官方清單：今年、明年還沒有資料，或官方換了新版（例如年中改了假日）就重抓。
"""
import csv
import datetime
import io
import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

from . import db
from .queries import today

DATASET = "https://data.gov.tw/api/v2/rest/dataset/14718"
MIRROR = "https://cdn.jsdelivr.net/gh/ruyut/TaiwanCalendar/data/%d.json"
OFFICIAL = "人事行政總處"
CHECK_EVERY = 6 * 3600          # 每個 worker 多久看一次要不要更新（只讀資料庫）
FETCH_EVERY = 86400             # 真的去官方清單看，一天最多一次
_checked = 0
_running = threading.Lock()


class CalendarError(Exception):
    """抓不到或格式不對：訊息可以直接給管理者看。"""


def _get(url, timeout=20):
    # 政府網站的憑證少了一個欄位，Python 3.13 以後預設的嚴格檢查會擋掉；憑證還是照樣驗證，只是不要那麼嚴格
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    url = urllib.parse.quote(url, safe=":/?&=%#")         # 官方網址的檔名參數有中文
    req = urllib.request.Request(url, headers={"User-Agent": "163braces-info"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read()
    except (OSError, ValueError) as e:
        raise CalendarError("連不到 %s（%s）" % (url.split("/")[2], e))


# ==================================================================== 讀資料
def official_files():
    """官方清單：{西元年: 下載網址}。同一年有好幾份（後來更正過）時用最新的一份，Google 行事曆專用的不要。"""
    try:
        items = json.loads(_get(DATASET))["result"]["distribution"]
    except (KeyError, TypeError, ValueError):
        raise CalendarError("政府資料開放平台的回應格式看不懂。")
    found = {}
    for i, it in enumerate(items):
        title, url = it.get("resourceDescription") or "", it.get("resourceDownloadUrl") or ""
        m = re.match(r"\s*(\d{2,3})\s*年", title)
        if not m or "Google" in title or not url.startswith("https://"):
            continue
        # 網址裡有上傳的年月（files/202510/…），越新越後面；一樣就看清單順序
        uploaded = re.search(r"files/(\d{6})/", url)
        rank = (uploaded.group(1) if uploaded else "", i)
        year = int(m.group(1)) + 1911
        if year not in found or rank > found[year][0]:
            found[year] = (rank, url)
    return {y: url for y, (rank, url) in found.items()}


def parse_csv(data):
    """官方 CSV（新的是 UTF-8，舊的是 Big5）→ [(YYYY-MM-DD, 放假 0/1, 說明)]。"""
    for enc in ("utf-8-sig", "cp950"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise CalendarError("CSV 的文字編碼看不懂。")
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.strip() for h in rows[0]] if rows else []
    try:
        di, oi = head.index("西元日期"), head.index("是否放假")
    except ValueError:
        raise CalendarError("CSV 的欄位不對：要有「西元日期」和「是否放假」。")
    ni = head.index("備註") if "備註" in head else None
    out = []
    for r in rows[1:]:
        if len(r) <= max(di, oi) or not re.fullmatch(r"\d{8}", r[di].strip()):
            continue
        d = r[di].strip()
        note = r[ni].strip() if ni is not None and len(r) > ni else ""
        out.append(("%s-%s-%s" % (d[:4], d[4:6], d[6:]), 1 if r[oi].strip() == "2" else 0, note))
    return out


def parse_mirror(data):
    try:
        return [("%s-%s-%s" % (d["date"][:4], d["date"][4:6], d["date"][6:8]), 1 if d["isHoliday"] else 0,
                 (d.get("description") or "").strip()) for d in json.loads(data)]
    except (KeyError, TypeError, ValueError):
        raise CalendarError("備用來源的格式看不懂。")


def _check(days):
    """要剛好是完整的一年（每一天都有），才不會存進半套資料。回傳年份。"""
    years = {d[:4] for d, off, note in days}
    if len(years) != 1:
        raise CalendarError("資料不是剛好一整年。")
    year = int(years.pop())
    first = datetime.date(year, 1, 1)
    want = {(first + datetime.timedelta(i)).isoformat() for i in range((datetime.date(year + 1, 1, 1) - first).days)}
    if {d for d, off, note in days} != want:
        raise CalendarError("%d 年的資料缺了幾天。" % year)
    return year


# ==================================================================== 存資料
def save_year(con, days, source, url=""):
    year = _check(days)
    con.execute("DELETE FROM calendar_days WHERE date LIKE ?", ("%d-%%" % year,))
    con.executemany("INSERT INTO calendar_days (date, off, note) VALUES (?, ?, ?)", days)
    con.execute("INSERT OR REPLACE INTO calendar_years (year, source, url, fetched_at) VALUES (?, ?, ?, ?)",
                (year, source, url, db.now()))
    con.commit()
    return year


def refresh(con, only_missing=False):
    """抓官方資料存起來；官方沒有的今年、明年改抓備用來源。回傳 (更新了哪些年, 錯誤訊息清單)。
    only_missing：只抓沒有的年份，或官方換了新版的今年以後的年份（每天自動檢查用）。"""
    this_year = int(today()[:4])
    have = {r["year"]: r for r in con.execute("SELECT * FROM calendar_years")}
    done, errors = [], []
    try:
        files = official_files()
    except CalendarError as e:
        files, errors = {}, ["官方清單：%s" % e]
    for year, url in sorted(files.items()):
        old = have.get(year)
        if only_missing and old and (year < this_year or (old["source"] == OFFICIAL and old["url"] == url)):
            continue
        try:
            done.append(save_year(con, parse_csv(_get(url)), OFFICIAL, url))
        except CalendarError as e:
            errors.append("%d 年（官方）：%s" % (year, e))
    # 官方還沒有（或這次抓失敗）的今年、明年：改抓備用來源。已經有官方資料的不拿備用的蓋掉
    for year in (this_year, this_year + 1):
        old = have.get(year)
        if year in done or (old and (old["source"] == OFFICIAL or only_missing)):
            continue
        try:
            done.append(save_year(con, parse_mirror(_get(MIRROR % year)), "ruyut/TaiwanCalendar", MIRROR % year))
        except CalendarError as e:
            if not old:
                errors.append("%d 年（備用來源）：%s%s" % (year, e, "，官方可能還沒公布" if year > this_year else ""))
    return sorted(set(done)), errors


# ==================================================================== 給頁面用
def years(con):
    return [r["year"] for r in con.execute("SELECT year FROM calendar_years ORDER BY year")]


def year_rows(con):
    """後台列表：每年幾天放假、從哪裡來。"""
    return con.execute(
        "SELECT y.*, (SELECT COUNT(*) FROM calendar_days d WHERE d.date LIKE y.year || '-%' AND d.off = 1) AS off_days "
        "FROM calendar_years y ORDER BY y.year DESC").fetchall()


def named_days(con, year):
    return con.execute("SELECT * FROM calendar_days WHERE date LIKE ? AND note != '' ORDER BY date",
                       ("%d-%%" % year,)).fetchall()


def marks(con, want_years):
    """前台行事曆：{"years": [有資料的年份], "days": {日期: [放假 0/1, 說明]}}。
    只列跟「週六日放假、平日上班」不一樣的日子，以及有名稱的日子。"""
    have = [y for y in years(con) if y in want_years]
    days = {}
    for y in have:
        for r in con.execute("SELECT * FROM calendar_days WHERE date LIKE ?", ("%d-%%" % y,)):
            weekend = datetime.date.fromisoformat(r["date"]).weekday() >= 5
            if r["note"] or bool(r["off"]) != weekend:
                days[r["date"]] = [r["off"], r["note"]]
    return {"years": have, "days": days}


def missing_years(con):
    """後台要提醒的年份：今年，以及還有演出卻沒有放假資料的年份。"""
    have = set(years(con))
    want = {int(today()[:4])}
    want |= {int(r[0]) for r in con.execute("SELECT DISTINCT substr(event_date, 1, 4) FROM performances "
                                            "WHERE event_date >= ?", (today()[:4],))}
    return sorted(want - have)


# ==================================================================== 自動更新（正式站）
def _daily():
    if not _running.acquire(blocking=False):
        return
    con = db.connect()
    try:
        last = db.get_setting(con, "holidays_checked_at")
        if last and time.time() - float(last) < FETCH_EVERY:
            return
        db.set_setting(con, "holidays_checked_at", str(time.time()))
        con.commit()
        done, errors = refresh(con, only_missing=True)
        if done:
            from . import pagecache
            pagecache.invalidate()
    except Exception:        # 背景工作：失敗就等明天再試，後台總覽會提醒缺哪一年
        pass
    finally:
        con.close()
        _running.release()


def maybe_daily():
    """每個請求都會呼叫，但每幾小時才真的看一次；抓資料在背景跑，不會拖慢這次請求。"""
    global _checked
    if not db.ON_AZURE or time.time() - _checked < CHECK_EVERY:
        return
    _checked = time.time()
    threading.Thread(target=_daily, daemon=True).start()
