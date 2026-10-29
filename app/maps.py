"""場地的 Google Maps 連結 → 座標。

認得的寫法：
- 網址裡有地點圖釘 !3d緯度!4d經度（最準，優先用）或畫面中心 @緯度,經度
- 短網址 maps.app.goo.gl/…（手機「分享」）：問 Google 轉到哪裡，從轉到的網址讀
- 直接貼座標「24.1790, 120.6467」（Google 地圖按右鍵第一行就是）
只有搜尋結果點進去的那種（網址只有 !1s0x0:0x… 地點編號）裡面沒有座標，讀不到。
"""
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

PIN = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
VIEW = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
QUERY = re.compile(r"[?&](?:q|query|ll|center)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+)", re.I)
PLAIN = re.compile(r"^\(?\s*(-?\d{1,2}\.\d+)\s*[,，]\s*(-?\d{1,3}\.\d+)\s*\)?$")
SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl", "g.co"}


class MapLinkError(ValueError):
    pass


def _google(host):
    return host in SHORT_HOSTS or bool(re.fullmatch(r"(?:[a-z0-9-]+\.)*google\.(?:com|com\.tw|[a-z]{2,3}(?:\.[a-z]{2})?)", host))


def _valid(lat, lng):
    lat, lng = float(lat), float(lng)
    return (round(lat, 6), round(lng, 6)) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


def _from_url(url):
    for rx in (PIN, VIEW, QUERY):
        m = rx.search(url)
        if m and _valid(*m.groups()):
            return _valid(*m.groups())
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):     # 不自動跟過去，自己一步一步看轉到哪
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _next(url):
    # 不要假裝成瀏覽器：用瀏覽器的 User-Agent，Google 會回一個要跑 JavaScript 才會跳轉的網頁
    req = urllib.request.Request(url, headers={"User-Agent": "163braces-info"})
    try:
        with _opener.open(req, timeout=8):
            return None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return urljoin(url, e.headers["Location"])
        if e.code in (400, 404, 410):
            raise MapLinkError("這條短網址打不開，請確認有沒有複製完整。")
        raise MapLinkError("Google 回應 %d，請稍後再試。" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise MapLinkError("連不到 Google，請稍後再試。")


def resolve(text):
    """連結或座標文字 → (要存的連結, 緯度, 經度)。讀不到就丟 MapLinkError（訊息可以直接給管理者看）。"""
    text = (text or "").strip()
    m = PLAIN.match(text)
    if m and _valid(*m.groups()):
        return ("",) + _valid(*m.groups())
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not _google(parts.hostname or ""):
        raise MapLinkError("這不是 Google 地圖的連結。")
    url = text
    for _ in range(5):
        ll = _from_url(url)
        if ll:
            return (text,) + ll
        if (urlsplit(url).hostname or "") not in SHORT_HOSTS:
            break
        url = _next(url)
        if not url or not _google(urlsplit(url).hostname or ""):
            break
    raise MapLinkError("這條連結裡沒有座標。請在 Google 地圖打開這個地點，按「分享」→「複製連結」再貼一次。")


def search_url(lat, lng):
    """沒有原始連結、只有座標時，前台連到 Google 地圖用的網址。"""
    return "https://www.google.com/maps/search/?api=1&query=%s,%s" % (lat, lng)
