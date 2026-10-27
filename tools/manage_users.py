"""後台帳號：忘記密碼、或新環境第一次建立帳號時用。

    python -m tools.manage_users list
    python -m tools.manage_users set-password 帳號      # 帳號不存在就新建
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import auth, db  # noqa: E402


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "set-password"):
        sys.exit(__doc__)
    con = db.connect()
    db.init(con)
    if sys.argv[1] == "list":
        for r in con.execute("SELECT username, is_active, last_login FROM users ORDER BY id"):
            print("%s\t%s\t最近登入 %s" % (r["username"], "啟用" if r["is_active"] else "停用", r["last_login"] or "—"))
        return
    if len(sys.argv) < 3:
        sys.exit("請給帳號名稱")
    name = sys.argv[2]
    password = getpass.getpass("新密碼（至少 8 個字元）：")
    if password != getpass.getpass("再輸入一次："):
        sys.exit("兩次輸入不一樣")
    row = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
    if row:
        auth.set_password(con, row["id"], password)
        print("已更新 %s 的密碼" % name)
    else:
        if len(password) < 8:
            sys.exit("密碼至少 8 個字元")
        con.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                    (name, auth.hash_password(password), db.now()))
        con.commit()
        print("已建立帳號 %s" % name)


if __name__ == "__main__":
    main()
