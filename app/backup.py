"""資料庫每週備份。

備份存在資料庫旁邊的 backups/（Azure 上是 /home/data/backups/，重新部署也不會清掉），保留最近 KEEP 份。
用 SQLite 的 backup API 複製，網站開著、有人正在寫入也能安全備份。

自動備份只在 Azure 上跑：每個 worker 每小時看一次，最新一份超過 7 天就再備份一份
（沒人來看網站的時候不會備份，但那段時間資料也不會變）。本機只能從後台手動按。
"""
import datetime
import os
import re
import sqlite3
import threading
import time

from . import db
from .queries import TZ

KEEP = 12                       # 每週一份，大約三個月
EVERY = 7 * 86400
DIR = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "backups")
NAME = re.compile(r"^site-\d{8}-\d{6}\.sqlite3$")
_checked = 0


def list_backups():
    """最新的在前：[{name, size, time（台灣時間字串）, mtime}]"""
    if not os.path.isdir(DIR):
        return []
    out = []
    for name in os.listdir(DIR):
        if NAME.match(name):
            st = os.stat(os.path.join(DIR, name))
            out.append({"name": name, "size": st.st_size, "mtime": st.st_mtime,
                        "time": datetime.datetime.fromtimestamp(st.st_mtime, TZ).strftime("%Y/%m/%d %H:%M")})
    return sorted(out, key=lambda b: b["name"], reverse=True)


def path_of(name):
    """下載用：只接受備份檔的檔名，不能用 ../ 之類跑到別的地方。"""
    return os.path.join(DIR, name) if NAME.match(name or "") and os.path.isfile(os.path.join(DIR, name)) else None


def create():
    """現在備份一份，回傳檔名。先寫到暫存檔再改名，備到一半當掉也不會留下壞掉的備份。"""
    os.makedirs(DIR, exist_ok=True)
    name = "site-%s.sqlite3" % datetime.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    tmp = os.path.join(DIR, name + ".tmp")
    src, dst = db.connect(), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, os.path.join(DIR, name))
    for old in list_backups()[KEEP:]:
        os.remove(os.path.join(DIR, old["name"]))
    return name


def _weekly():
    lock = os.path.join(DIR, ".lock")
    try:
        os.makedirs(DIR, exist_ok=True)
        latest = list_backups()[:1]
        if latest and time.time() - latest[0]["mtime"] < EVERY:
            return
        # 兩個 worker 可能同時發現該備份了：先建得出 .lock 的那個才做（十分鐘以前留下的 .lock 當作沒有）
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > 600:
            os.remove(lock)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return
    try:
        os.close(fd)
        create()
    finally:
        os.remove(lock)


def maybe_weekly():
    """每個請求都會呼叫，但每小時才真的看一次；備份在背景跑，不會拖慢這次請求。"""
    global _checked
    if not db.ON_AZURE or time.time() - _checked < 3600:
        return
    _checked = time.time()
    threading.Thread(target=_weekly, daemon=True).start()
