"""頁面樹：跟舊站（Wagtail）一樣，每一頁都掛在某一頁底下（parent_id），首頁是根。

網址＝上層頁面的網址＋自己那一段，例如「文章」（articles）底下的 fanpages 就是 /articles/fanpages/。
pages.slug 仍然存完整路徑（前台照 slug 找頁面，不用每次往上算）；搬移或改網址時由 move() 一次把
這一頁和底下所有頁面的 slug 改好，並留下舊網址的轉址。

歌詞（lyrics 表）與演出頁的分頁不是 pages 裡的頁面，但網址也在歌詞索引、演出頁底下，搬移時一起處理轉址。
"""
from . import navigation, queries as Q

# 樹狀列表裡兄弟頁面的順序：固定頁面在前，再照後台填的排序、文章照發佈日期新到舊
KIND_ORDER = {"home": 0, "performances": 1, "lyrics": 2, "articles": 3, "page": 4, "article": 5}


def join(parent_slug, segment):
    return segment if not parent_slug else parent_slug + "/" + segment


def segment_of(page, parent):
    """這一頁自己那一段網址（不含上層）。"""
    if not parent or not parent["slug"]:
        return page["slug"]
    return page["slug"][len(parent["slug"]) + 1:]


def ensure_schema(con):
    """舊的資料庫沒有 parent_id：加上欄位，再依現有的網址推出上下層關係。"""
    cols = [r["name"] for r in con.execute("PRAGMA table_info(pages)")]
    if "parent_id" not in cols:
        con.execute("ALTER TABLE pages ADD COLUMN parent_id INTEGER REFERENCES pages(id)")
    if con.execute("SELECT 1 FROM pages WHERE parent_id IS NULL AND kind != 'home' LIMIT 1").fetchone():
        rebuild_parents(con)
        con.commit()


def rebuild_parents(con):
    """還沒有上層的頁面：網址前綴最長的那一頁就是它的上層（articles/fanpages → articles），找不到就掛在首頁。"""
    pages = con.execute("SELECT id, slug, kind FROM pages").fetchall()
    home = next((p["id"] for p in pages if p["kind"] == "home"), None)
    for p in pages:
        if p["kind"] == "home":
            continue
        candidates = [q for q in pages if q["id"] != p["id"] and q["slug"] and p["slug"].startswith(q["slug"] + "/")]
        parent = max(candidates, key=lambda q: len(q["slug"]))["id"] if candidates else home
        con.execute("UPDATE pages SET parent_id = ? WHERE id = ? AND parent_id IS NULL", (parent, p["id"]))


def _sort_key(p):
    # 文章新的排前面：日期轉成數字取負號
    newest_first = -int((p["published_at"] or "0").replace("-", "")[:8] or 0) if p["kind"] == "article" else 0
    return (KIND_ORDER.get(p["kind"], 9), p["sort_order"], newest_first, p["id"])


def tree(con):
    """深度優先的 (頁面, 層數) 列表，首頁在最上面（第 0 層）。"""
    pages = con.execute("SELECT * FROM pages").fetchall()
    children = {}
    for p in pages:
        children.setdefault(p["parent_id"], []).append(p)
    out, seen = [], set()

    def walk(p, depth):
        if p["id"] in seen:          # 防呆：資料若有循環，不要無限遞迴
            return
        seen.add(p["id"])
        out.append((p, depth))
        for c in sorted(children.get(p["id"], []), key=_sort_key):
            walk(c, depth + 1)
    for root in sorted(children.get(None, []), key=_sort_key):
        walk(root, 0)
    for p in sorted(pages, key=_sort_key):      # 掛在不存在的上層底下的孤兒頁面，接在最後
        if p["id"] not in seen:
            walk(p, 1)
    return out


def descendants(con, page_id):
    rows, frontier = [], [page_id]
    while frontier:
        found = con.execute("SELECT * FROM pages WHERE parent_id IN (%s)" % ",".join("?" * len(frontier)),
                            frontier).fetchall()
        rows += found
        frontier = [r["id"] for r in found]
    return rows


def has_children(con, page_id):
    return bool(con.execute("SELECT 1 FROM pages WHERE parent_id = ? LIMIT 1", (page_id,)).fetchone())


class MoveError(Exception):
    pass


def move(con, page, parent, segment, add_redirects):
    """把 page 搬到 parent 底下、網址那一段改成 segment；底下的頁面跟著改網址，舊網址都轉到新網址。
    add_redirects(old_url, new_url) 由呼叫端提供（admin.add_redirects）。"""
    if parent and (parent["id"] == page["id"] or parent["id"] in {d["id"] for d in descendants(con, page["id"])}):
        raise MoveError("不能把頁面搬到它自己或它底下的頁面裡。")
    old = page["slug"]
    new = join(parent["slug"] if parent else "", segment)
    moving = [page] + descendants(con, page["id"])
    new_slugs = {p["id"]: new + p["slug"][len(old):] if p["id"] != page["id"] else new for p in moving}
    ids = list(new_slugs)
    for pid, slug in new_slugs.items():
        clash = con.execute("SELECT id FROM pages WHERE slug = ? AND id NOT IN (%s)" % ",".join("?" * len(ids)),
                            [slug] + ids).fetchone()
        if clash:
            raise MoveError("網址「/%s/」已經有別的頁面在用。" % slug)
    reserved = [u for tab, u in Q.tab_urls(con).items() if tab != "list"]
    for slug in new_slugs.values():
        if "/%s/" % slug in reserved:
            raise MoveError("「/%s/」是演出頁分頁的網址，請換一個。" % slug)

    con.execute("UPDATE pages SET parent_id = ? WHERE id = ?", (parent["id"] if parent else None, page["id"]))
    if new == old:
        return
    # 先暫時改成不會撞名的值，再改成新網址（UNIQUE 限制在逐筆更新時可能互撞）
    for pid in ids:
        con.execute("UPDATE pages SET slug = ? WHERE id = ?", ("__moving__/%d" % pid, pid))
    for p in moving:
        con.execute("UPDATE pages SET slug = ? WHERE id = ?", (new_slugs[p["id"]], p["id"]))
        old_url, new_url = Q.page_url(p), Q.page_url({"slug": new_slugs[p["id"]]})
        add_redirects(con, old_url, new_url)
        if p["kind"] == "performances":          # 統計、歌單分頁在演出頁底下，一起轉
            for sub in Q.TAB_SUBPATHS.values():
                add_redirects(con, old_url + sub + "/", new_url + sub + "/")
        if p["kind"] == "lyrics":                # 每首歌詞都在歌詞索引底下，一起轉
            for l in con.execute("SELECT slug FROM lyrics"):
                add_redirects(con, old_url + l["slug"] + "/", new_url + l["slug"] + "/")
    # 選單、頁尾裡用自訂網址寫死的站內連結（連頁面的會自動跟著走）
    navigation.rewrite_urls(con, Q.page_url(page), Q.page_url({"slug": new}))


def nested(con):
    """後台列表用的巢狀結構：[{page, children: [...]}]。
    首頁跟它底下的頁面排在同一層（首頁本身不展開），更深的頁面收在各自的上層底下。"""
    pages = con.execute("SELECT * FROM pages").fetchall()
    children = {}
    for p in pages:
        children.setdefault(p["parent_id"], []).append(p)
    seen = set()

    def build(p):
        seen.add(p["id"])
        return {"page": p, "children": [build(c) for c in sorted(children.get(p["id"], []), key=_sort_key)
                                        if c["id"] not in seen]}
    top = []
    for root in sorted(children.get(None, []), key=_sort_key):
        if root["kind"] == "home":
            seen.add(root["id"])
            top.append({"page": root, "children": []})
            top += [build(c) for c in sorted(children.get(root["id"], []), key=_sort_key)]
        else:
            top.append(build(root))
    top += [build(p) for p in sorted(pages, key=_sort_key) if p["id"] not in seen]    # 上層不見了的孤兒頁面
    return top
