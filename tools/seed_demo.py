"""在本機資料庫放一些模擬的粉絲留言（首頁跑馬燈），看版面效果用。

    python -m tools.seed_demo            # 加入模擬的粉絲帳號與跑馬燈留言（重複執行會先清掉舊的再加）
    python -m tools.seed_demo --clear    # 全部清掉

模擬的帳號 google_sub 都以 demo: 開頭，--clear 只刪這些帳號（留言跟著刪），不會動到真的資料。
正式站的資料是從舊站轉檔來的，不會有這些模擬資料；不要在正式站執行。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db, visitors  # noqa: E402

# (帳號, Google 名字, 暱稱)
FANS = [
    ("demo:1", "陳怡君", "海螺收集者"),
    ("demo:2", "Lin Wei", ""),
    ("demo:3", "王小美", "小美"),
    ("demo:4", "Chen Yu-Ting", "Tina"),
    ("demo:5", "張家豪", ""),
    ("demo:6", "Kana Sato", "かな"),
]

# (哪位粉絲, 署名方式, 留言, 幾小時前)
POSTS = [
    (0, "nickname", "海螺記每一首都好喜歡，天天循環", 2),
    (1, "google", "Moon and Tides live version gave me chills", 5),
    (2, "nickname", "第一次去專場就被〈潮汐〉唱哭了", 9),
    (3, "anonymous", "希望有一天能在台南看到 163", 14),
    (4, "google", "期待下一張專輯！", 20),
    (5, "nickname", "Love from Japan, see you in Taipei", 26),
    (0, "nickname", "謝謝整理歌單的大家 辛苦了", 31),
    (2, "anonymous", "〈鳥〉的 Bridge 現場版更好聽", 40),
    (3, "nickname", "Brace Up 每次聽都充滿力量", 52),
    (1, "anonymous", "Can't wait for the next show", 60),
    (4, "google", "校園巡迴來我們學校好不好", 75),
    (5, "google", "〈找〉的日文版也太好聽了吧", 90),
]


def clear(con):
    n = con.execute("SELECT COUNT(*) FROM visitors WHERE google_sub LIKE 'demo:%'").fetchone()[0]
    con.execute("DELETE FROM visitors WHERE google_sub LIKE 'demo:%'")      # 留言、紀錄跟著刪（ON DELETE CASCADE）
    con.commit()
    return n


def seed(con):
    clear(con)
    ids = []
    for sub, name, nickname in FANS:
        vid = visitors.upsert_visitor(con, sub, "", name, "")
        con.execute("UPDATE visitors SET nickname = ? WHERE id = ?", (nickname, vid))
        ids.append(vid)
    now = datetime.datetime.now()
    for fan, mode, text, hours in POSTS:
        assert visitors.text_units(text) <= visitors.MARQUEE_MAX_UNITS, text
        stamp = (now - datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
        con.execute("INSERT INTO marquee_posts (visitor_id, text, name_mode, created_at) VALUES (?, ?, ?, ?)",
                    (ids[fan], text, mode, stamp))
    con.commit()
    return len(FANS), len(POSTS)


def main():
    if db.ON_AZURE:
        sys.exit("這是給本機看效果用的，不要在正式站執行。")
    con = db.connect()
    db.init(con)
    if "--clear" in sys.argv:
        print("已刪除 %d 個模擬帳號與他們的留言" % clear(con))
    else:
        fans, posts = seed(con)
        print("已加入 %d 個模擬帳號、%d 則跑馬燈留言（%s）" % (fans, posts, db.DB_PATH))


if __name__ == "__main__":
    main()
