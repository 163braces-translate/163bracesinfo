"""訪客（粉絲）登入：Google 帳號。

流程（OAuth 2.0 授權碼流程，加 PKCE）：
1. /auth/google/login：產生隨機的 state 與 PKCE verifier，放進短效 cookie，把人送到 Google 的登入頁。
2. 使用者在 Google 按同意，Google 帶著一次性 code 送回 /auth/google/callback。
3. 我們比對 state（擋掉偽造的回呼），用 code＋verifier＋client secret 向 Google 換 id_token。
4. id_token 是我們的伺服器直接透過 HTTPS 跟 Google 拿的，Google 文件說這種情況可以不驗簽章；
   仍檢查發行者、對象（aud＝我們的 client id）與到期時間。從裡面取出帳號 ID（sub）、email、名字、大頭貼。
5. 用 sub 找訪客，沒有就建一筆；發 vsid cookie（資料庫只存它的 SHA-256），跟後台的登入完全分開。

需要的環境變數（在 Google Cloud Console 建立「OAuth 用戶端 ID」取得）：
  GOOGLE_CLIENT_ID、GOOGLE_CLIENT_SECRET
沒設定時「用 Google 登入」不會出現。

本機開發：設 DEV_LOGIN=1 會多一個「測試登入」（輸入名字就登入），不用真的接 Google。
在 Azure 上（有 WEBSITE_SITE_NAME）一律關閉，就算誤設了 DEV_LOGIN 也一樣。
"""
import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request

from . import db

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

DEV_LOGIN = os.environ.get("DEV_LOGIN") == "1" and not db.ON_AZURE

COOKIE = "vsid"
STATE_COOKIE = "oauth_state"
SESSION_DAYS = 60

# 每個人 24 小時內最多投幾次，避免洗版
DAILY_LIMITS = {"marquee": 3, "contribution": 10, "sheet": 5, "show": 5}
MARQUEE_MAX_UNITS = 30
MARQUEE_MAX_CHARS = 120        # 單位怎麼算都不能超過的總字元數（擋掉一堆符號、表情）


class LoginError(Exception):
    """訊息直接顯示給使用者。"""


def google_enabled():
    return bool(CLIENT_ID and CLIENT_SECRET)


def login_available():
    return True             # 訪客（自取暱稱）登入一直都可以用，見 is_guest()


GUEST_HOURS = 24


def is_guest(visitor):
    """訪客：在登入頁自取暱稱、不用 Google 的臨時帳號（google_sub 是 guest:…）。
    可以標記去過的場次、按喜歡，但只在他自己的「我的」裡有意義：網站上的總數不算訪客（community.COUNTED）。
    不能投稿、不能開公開個人頁。登入 24 小時後失效，之後回不到這個帳號。"""
    return bool(visitor) and visitor["google_sub"].startswith("guest:")


def guest_expires(visitor):
    return datetime.datetime.fromisoformat(visitor["session_created"]) + datetime.timedelta(hours=GUEST_HOURS)


# ==================================================================== Google OAuth
def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def start_login():
    """回傳 (state, verifier, code_challenge)。state 與 verifier 要放進 cookie，回呼時比對。"""
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    return state, verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def google_auth_url(state, challenge, redirect_uri):
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "prompt": "select_account",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def google_exchange(code, verifier, redirect_uri):
    """用一次性 code 換 id_token，回傳裡面的使用者資料（dict）。"""
    body = urllib.parse.urlencode({
        "code": code, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code", "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read())
    except Exception:
        raise LoginError("跟 Google 確認登入時出錯，請再試一次。")
    try:
        payload = token["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (KeyError, IndexError, ValueError):
        raise LoginError("Google 回傳的登入資料讀不懂，請再試一次。")
    if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != CLIENT_ID or claims.get("exp", 0) < time.time():
        raise LoginError("登入資料驗證失敗，請再試一次。")
    return claims


# ==================================================================== 訪客與登入狀態
def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def upsert_visitor(con, sub, email="", name="", avatar=""):
    row = con.execute("SELECT * FROM visitors WHERE google_sub = ?", (sub,)).fetchone()
    stamp = db.now()
    if row:
        con.execute("UPDATE visitors SET email = ?, google_name = ?, avatar_url = ?, last_login = ? WHERE id = ?",
                    (email, name, avatar, stamp, row["id"]))
        return row["id"]
    return con.execute("INSERT INTO visitors (google_sub, email, google_name, avatar_url, created_at, last_login) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (sub, email, name, avatar, stamp, stamp)).lastrowid


def create_session(con, visitor_id):
    token = secrets.token_urlsafe(32)
    stamp = db.now()
    con.execute("INSERT INTO visitor_sessions VALUES (?, ?, ?, ?)", (_sha(token), visitor_id, stamp, stamp))
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    con.execute("DELETE FROM visitor_sessions WHERE created_at < ?", (cutoff,))
    con.commit()
    return token


def current_visitor(con, token):
    if not token:
        return None
    row = con.execute("SELECT v.*, s.created_at AS session_created FROM visitor_sessions s "
                      "JOIN visitors v ON v.id = s.visitor_id WHERE s.token_hash = ?", (_sha(token),)).fetchone()
    if not row:
        return None
    limit = datetime.timedelta(hours=GUEST_HOURS) if is_guest(row) else datetime.timedelta(days=SESSION_DAYS)
    if datetime.datetime.fromisoformat(row["session_created"]) < datetime.datetime.now() - limit:
        end_session(con, token)
        return None
    return row


def end_session(con, token):
    if token:
        con.execute("DELETE FROM visitor_sessions WHERE token_hash = ?", (_sha(token),))
        con.commit()


def delete_visitor(con, visitor_id):
    """刪除帳號：連同去過的場次、喜歡的歌、跑馬燈、投稿、樂譜圖檔一起刪掉。已經被核准套用的演出資料不會回復。"""
    files = [r["file"] for r in con.execute(
        "SELECT f.file FROM sheet_files f JOIN sheets s ON s.id = f.sheet_id WHERE s.visitor_id = ?", (visitor_id,))]
    con.execute("DELETE FROM visitors WHERE id = ?", (visitor_id,))      # 其他表都是 ON DELETE CASCADE
    con.commit()
    remove_media(files)


def delete_sheet(con, sheet_id):
    """整份樂譜連同圖檔刪掉（管理者處理投稿者的刪除要求、修改版取代原本那份）。
    修改版會沿用原本的圖檔，所以只刪沒有別份樂譜在用的檔案。"""
    files = [r["file"] for r in con.execute("SELECT file FROM sheet_files WHERE sheet_id = ?", (sheet_id,))]
    con.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))          # sheet_files 是 ON DELETE CASCADE
    con.commit()
    remove_unused_media(con, files)


def remove_unused_media(con, files):
    remove_media([f for f in files if not con.execute("SELECT 1 FROM sheet_files WHERE file = ?", (f,)).fetchone()])


def remove_media(files):
    for f in files:
        for path in (os.path.join(db.MEDIA_ROOT, f), sheet_thumb_path(f)):
            if os.path.isfile(path):
                os.remove(path)


def sheet_thumb_path(file):
    """樂譜圖檔的縮圖（歌詞頁的樂譜卡片用），第一次要用時才產生。"""
    return os.path.join(db.MEDIA_ROOT, "cache", file.replace("/", "-").rsplit(".", 1)[0] + "-thumb.jpg")


# ==================================================================== 署名、字數、投稿頻率
NAME_MODES = ("google", "nickname", "anonymous")


def display_name(row, mode, anonymous_label):
    """投稿的署名。row 要有 google_name 與 nickname 欄位（訪客，或 JOIN 了訪客的投稿）。"""
    if mode == "google" and row["google_name"]:
        return row["google_name"]
    if mode == "nickname" and row["nickname"]:
        return row["nickname"]
    return anonymous_label


def text_units(text):
    """跑馬燈的字數：一個中文（日文、韓文）字算 1，一個英文單字（或一串數字）算 1；標點、空白、表情符號不算。"""
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿豈-﫿가-힯]", text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*", text))
    return cjk + words


def over_daily_limit(con, kind, visitor_id):
    table = {"marquee": "marquee_posts", "contribution": "contributions", "sheet": "sheets", "show": "show_submissions"}[kind]
    since = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    n = con.execute("SELECT COUNT(*) FROM %s WHERE visitor_id = ? AND created_at >= ?" % table,
                    (visitor_id, since)).fetchone()[0]
    return n >= DAILY_LIMITS[kind]


HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{2,29}")


def check_handle(handle):
    handle = (handle or "").strip().lower()
    if not HANDLE_RE.fullmatch(handle):
        raise LoginError("個人頁網址要 3–30 個字，只能用英文小寫、數字、- 和 _，開頭要是英文或數字。")
    return handle
