"""後台登入。

密碼：新設定的密碼用 scrypt（Python 內建）加隨機鹽，存成 scrypt$N$r$p$鹽$雜湊。
  舊站轉過來的帳號是 Django 的 pbkdf2_sha256$次數$鹽$雜湊，照樣能驗證；登入成功後自動換成 scrypt。
登入狀態：登入後發一組隨機憑證放在 HttpOnly cookie，資料庫只存它的 SHA-256。
  閒置 IDLE_HOURS 小時或登入滿 MAX_DAYS 天失效。不需要 SECRET_KEY。
暴力破解：同一帳號連續輸錯 MAX_FAILS 次，鎖 LOCK_MINUTES 分鐘（記在記憶體，重啟就清掉，夠用）。
"""
import base64
import datetime
import hashlib
import hmac
import secrets
import threading

from . import db

COOKIE = "sid"
IDLE_HOURS = 12
MAX_DAYS = 14
MAX_FAILS = 5
LOCK_MINUTES = 15
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

_fails = {}
_lock = threading.Lock()


class AuthError(Exception):
    """訊息直接顯示給使用者。"""


def hash_password(password):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P,
                                      base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_password(password, stored):
    try:
        algo = stored.split("$", 1)[0]
        if algo == "scrypt":
            _, n, r, p, salt, h = stored.split("$")
            want = base64.b64decode(h)
            got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                 dklen=len(want))
            return hmac.compare_digest(got, want)
        if algo == "pbkdf2_sha256":          # 舊站（Django）的格式
            _, iterations, salt, h = stored.split("$")
            got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
            return hmac.compare_digest(base64.b64encode(got).decode(), h)
    except (ValueError, TypeError):
        pass
    return False


def _now():
    return datetime.datetime.now()


def login(con, username, password):
    """成功回傳 cookie 憑證；失敗丟 AuthError。"""
    key = (username or "").strip().lower()
    with _lock:
        count, until = _fails.get(key, (0, None))
        if until and until > _now():
            raise AuthError("輸錯太多次，請 %d 分鐘後再試。" % LOCK_MINUTES)
    user = con.execute("SELECT * FROM users WHERE lower(username) = ? AND is_active = 1", (key,)).fetchone()
    if not user or not verify_password(password or "", user["password"]):
        with _lock:
            count += 1
            _fails[key] = (count, _now() + datetime.timedelta(minutes=LOCK_MINUTES) if count >= MAX_FAILS else None)
        raise AuthError("帳號或密碼錯誤。")
    with _lock:
        _fails.pop(key, None)
    if not user["password"].startswith("scrypt$"):
        con.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), user["id"]))
    token = secrets.token_urlsafe(32)
    stamp = db.now()
    con.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (_sha(token), user["id"], stamp, stamp))
    con.execute("UPDATE users SET last_login = ? WHERE id = ?", (stamp, user["id"]))
    con.execute("DELETE FROM sessions WHERE last_seen < ? OR created_at < ?",
                ((_now() - datetime.timedelta(hours=IDLE_HOURS)).isoformat(timespec="seconds"),
                 (_now() - datetime.timedelta(days=MAX_DAYS)).isoformat(timespec="seconds")))
    con.commit()
    return token


def current_user(con, token):
    if not token:
        return None
    row = con.execute("SELECT u.*, s.created_at AS session_created, s.last_seen FROM sessions s "
                      "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND u.is_active = 1",
                      (_sha(token),)).fetchone()
    if not row:
        return None
    now = _now()
    if (datetime.datetime.fromisoformat(row["last_seen"]) < now - datetime.timedelta(hours=IDLE_HOURS) or
            datetime.datetime.fromisoformat(row["session_created"]) < now - datetime.timedelta(days=MAX_DAYS)):
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))
        con.commit()
        return None
    # 每 5 分鐘以上才更新一次，免得每個請求都寫資料庫
    if datetime.datetime.fromisoformat(row["last_seen"]) < now - datetime.timedelta(minutes=5):
        con.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (db.now(), _sha(token)))
        con.commit()
    return row


def logout(con, token):
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))
        con.commit()


def set_password(con, user_id, password):
    if len(password or "") < 8:
        raise AuthError("密碼至少 8 個字元。")
    con.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), user_id))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    con.commit()


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()
