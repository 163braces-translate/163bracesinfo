"""沒登入的訪客看到的演出頁（含演出統計、歌單統計、年度回顧分頁）每個人都一樣：
算好的整頁（連同壓縮好的版本）存在記憶體裡，下一位直接給，人多的時候不用每次重算。

- 只存「沒有任何登入 cookie」的 GET 請求。登入的粉絲、管理者每次都即時算（頁面上有自己的「我去過」）。
- 後台有任何存檔（POST /admin/…）就全部作廢：資料庫 settings 裡記一個版本號（cache_version），
  每個處理程序（worker）看到版本號變了就清掉自己的快取，所以開好幾個 worker 也會一起更新。
- 每份最多保留 TTL 秒，日期換了也重算（「即將演出」的分界才不會停在昨天）。
  「幾位粉絲去過」這類數字對沒登入的訪客最多晚 TTL 秒更新。
- 部署新程式會重新啟動，記憶體清空，不會留著舊版。
"""
import gzip
import threading
import time
import uuid

from . import auth, db, queries as Q, visitors

TTL = 300
MAX_ENTRIES = 300           # 篩選條件的組合很多：存滿就全部清掉重來，記憶體不會一直長
_lock = threading.Lock()
_store = {}
_version = None
_building = {}              # 每一頁一把鎖：快取剛作廢時一堆人同時進來，只讓第一個人算，其他人等他算好


def anonymous(request):
    return request.method == "GET" and not (request.cookies.get(auth.COOKIE) or request.cookies.get(visitors.COOKIE))


def _sync(con):
    """其他 worker 處理了後台存檔：版本號變了，清掉這個 worker 的快取。"""
    global _version
    current = db.get_setting(con, "cache_version")
    if current != _version:
        with _lock:
            _store.clear()
            _version = current


def get(con, key):
    _sync(con)
    hit = _store.get(key)
    if hit and hit["expires"] > time.time() and hit["day"] == Q.today():
        return hit
    return None


def building(key):
    with _lock:
        return _building.setdefault(key, threading.Lock())


def put(key, body, media_type):
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            _store.clear()
        _store[key] = {"body": body, "gz": gzip.compress(body, compresslevel=6), "type": media_type,
                       "expires": time.time() + TTL, "day": Q.today()}


def invalidate():
    """後台存檔後呼叫：換一個新的版本號，所有 worker 下一個請求就會清掉快取。"""
    con = db.connect()
    try:
        db.set_setting(con, "cache_version", uuid.uuid4().hex)
        con.commit()
        _sync(con)
    finally:
        con.close()
