# -*- coding: utf-8 -*-
"""
写操作（POST）路由端到端检查 —— 重构验证用。

回归脚本 regression_reallib.py 只覆盖读取类页面（GET），而重构最容易出错的
恰恰是写操作：表单字段解析、批量操作、书架增删、导入提交。本脚本把全部
写路由真跑一遍，用真实书库做增删，最后**从备份完整还原并校验 md5**。

安全约定：
1. 跑之前先备份 data/library.json，结束后无条件还原；
2. 「用默认程序打开文件」「弹原生对话框」两处会真的产生副作用，
   测试中一律 mock 掉，绝不真开文件、绝不真弹窗。

用法：python tests/post_routes_check.py
退出码 0 = 全部通过且数据已干净还原。
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


import hashlib
import io
import json
import os
import shutil
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PUBLISH_DRY_RUN"] = "1"

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def main():
    import app as A
    import shelfmark.views.api as V_API
    import shelfmark.views.books as V_BOOKS

    lib = os.path.join(A.DATA_DIR, "library.json")
    backup = lib + ".pre_post_test"
    shutil.copy2(lib, backup)
    before_md5 = md5(lib)
    before_count = len(A.load_data()["books"])

    client = A.app.test_client()

    # 危险函数全部 mock：既不真开文件，也不真弹对话框
    with mock.patch.object(V_BOOKS, "open_file_with_default_app",
                           return_value=True), \
            mock.patch.object(V_API, "pick_file_dialog", return_value=None), \
            mock.patch.object(V_API, "pick_folder_dialog", return_value=None):

        # ---------- 1) 新增书籍 ----------
        r = client.post("/book/add", data={
            "title": "重构测试书", "author": "测试作者", "publisher": "测试社",
            "publish_year": "2020", "pages": "302", "isbn": "9780000000001",
            "file_format": "pdf", "status": "未读", "rating": "4",
            "tags": "测试,重构", "series": "测试丛书", "series_number": "1",
            "file_path": "", "subtitle": "", "blurb": "", "notes": "",
        }, follow_redirects=False)
        check("POST /book/add 重定向", r.status_code in (302, 303), str(r.status_code))
        data = A.load_data()
        added = [b for b in data["books"] if b["title"] == "重构测试书"]
        check("新增书籍已入库", len(added) == 1, "%d 条" % len(added))
        check("书库总数 +1", len(data["books"]) == before_count + 1,
              "%d → %d" % (before_count, len(data["books"])))
        if not added:
            return finish(lib, backup, before_md5)
        nb = added[0]
        check("页数已保存", str(nb.get("pages")) == "302", str(nb.get("pages")))
        check("标签已解析", sorted(nb.get("tags") or []) == ["测试", "重构"],
              str(nb.get("tags")))
        check("评分已保存", str(nb.get("rating")) == "4", str(nb.get("rating")))
        bid = nb["book_id"]

        # ---------- 2) 编辑书籍 ----------
        r = client.post("/book/edit/%s" % bid, data={
            "title": "重构测试书(改)", "author": "测试作者", "publisher": "新社",
            "publish_year": "2021", "pages": "410", "isbn": "9780000000001",
            "file_format": "epub", "status": "在读", "rating": "5",
            "tags": "测试", "series": "", "series_number": "", "file_path": "",
            "subtitle": "", "blurb": "", "notes": "",
        })
        check("POST /book/edit 重定向", r.status_code in (302, 303), str(r.status_code))
        eb = A.get_book(bid)
        check("编辑生效", eb and eb["title"] == "重构测试书(改)"
              and str(eb["pages"]) == "410" and eb["file_format"] == "epub",
              "%s / %s / %s" % (eb.get("title"), eb.get("pages"),
                                eb.get("file_format")) if eb else "无")

        # ---------- 3) 批量打标签 ----------
        r = client.post("/books/bulk/tags", data={
            "book_ids": bid, "tags": "批量A,批量B", "mode": "append"})
        check("POST /books/bulk/tags(append)", r.status_code in (302, 303),
              str(r.status_code))
        tags = set(A.get_book(bid).get("tags") or [])
        check("批量标签已追加", {"测试", "批量A", "批量B"} <= tags, str(sorted(tags)))
        r = client.post("/books/bulk/tags", data={
            "book_ids": bid, "tags": "只剩这个", "mode": "replace"})
        check("批量标签已替换",
              (A.get_book(bid).get("tags") or []) == ["只剩这个"],
              str(A.get_book(bid).get("tags")))

        # ---------- 4) 书架：创建 / 加书 / 移出 / 编辑 / 删除 ----------
        n_shelves = len(A.load_data().get("shelves") or [])
        r = client.post("/shelf/create", data={"name": "重构测试架", "kind": "normal"})
        check("POST /shelf/create", r.status_code in (302, 303), str(r.status_code))
        shelves = A.load_data().get("shelves") or []
        check("书架数 +1", len(shelves) == n_shelves + 1,
              "%d → %d" % (n_shelves, len(shelves)))
        mine = [s for s in shelves if s.get("name") == "重构测试架"]
        sid = mine[0]["id"] if mine else None

        r = client.post("/shelf/create", data={
            "name": "重构智能架", "kind": "smart", "rule_status": "已读",
            "rule_rating": "5", "rule_tags": "小说"})
        check("POST /shelf/create(smart)", r.status_code in (302, 303),
              str(r.status_code))

        if sid:
            r = client.post("/shelf/add", data={"shelf_id": sid, "book_id": bid})
            check("POST /shelf/add", r.status_code in (302, 303), str(r.status_code))
            s = [x for x in (A.load_data().get("shelves") or [])
                 if x["id"] == sid][0]
            check("书籍已加入书架", bid in (s.get("book_ids") or []),
                  str(len(s.get("book_ids") or [])))
            r = client.post("/shelf/%s/remove" % sid, data={"book_id": bid})
            check("POST /shelf/remove", r.status_code in (302, 303),
                  str(r.status_code))
            s = [x for x in (A.load_data().get("shelves") or [])
                 if x["id"] == sid][0]
            check("书籍已移出书架", bid not in (s.get("book_ids") or []))
            r = client.post("/shelf/%s/edit" % sid,
                            data={"name": "重构测试架(改)", "kind": "normal"})
            check("POST /shelf/edit", r.status_code in (302, 303),
                  str(r.status_code))
            s = [x for x in (A.load_data().get("shelves") or [])
                 if x["id"] == sid][0]
            check("书架改名生效", s["name"] == "重构测试架(改)", s["name"])

        # 删除自建的两个书架
        for s in (A.load_data().get("shelves") or []):
            if s.get("name", "").startswith("重构"):
                client.post("/shelf/%s/delete" % s["id"])
        left = [s for s in (A.load_data().get("shelves") or [])
                if s.get("name", "").startswith("重构")]
        check("POST /shelf/delete", not left, "剩余 %d" % len(left))

        # ---------- 5) 路径修正（错误前缀应给出提示且不改数据）----------
        r = client.post("/paths/run", data={
            "old_prefix": "", "new_prefix": "/tmp/x"})
        check("POST /paths/run 空前缀被拒", r.status_code in (302, 303),
              str(r.status_code))

        # ---------- 6) 作者国籍（本地解析，不联网）----------
        r = client.post("/nationality/run", data={"mode": "fill_empty"})
        check("POST /nationality/run", r.status_code in (302, 303),
              str(r.status_code))

        # ---------- 7) 导出 / 恢复 ----------
        r = client.get("/export")
        check("GET /export 返回 JSON 附件", r.status_code == 200
              and "json" in (r.headers.get("Content-Type") or "").lower(),
              (r.headers.get("Content-Type") or "")[:40])
        exported = r.get_data()
        try:
            json.loads(exported.decode("utf-8"))
            check("导出内容是合法 JSON", True)
        except Exception as e:
            check("导出内容是合法 JSON", False, repr(e))
        r = client.post("/restore", data={
            "mode": "merge",
            "file": (io.BytesIO(exported), "lib.json"),
        }, content_type="multipart/form-data")
        check("POST /restore(merge)", r.status_code in (302, 303),
              str(r.status_code))

        # ---------- 8) 对话框接口（已 mock，应优雅返回）----------
        r = client.get("/api/browse_file")
        j = r.get_json() or {}
        check("GET /api/browse_file 取消不报错",
              r.status_code == 200 and j.get("ok") is False,
              json.dumps(j, ensure_ascii=False)[:60])
        r = client.get("/api/browse_folder")
        check("GET /api/browse_folder 取消不报错", r.status_code == 200)

        # ---------- 9) 打开书籍（已 mock，不真开文件）----------
        r = client.get("/open/%s" % bid)
        check("GET /open 走通（已 mock）", r.status_code in (302, 303),
              str(r.status_code))

        # ---------- 10) 删除测试书 ----------
        r = client.post("/book/delete/%s" % bid)
        check("POST /book/delete", r.status_code in (302, 303), str(r.status_code))
        check("测试书已删除", A.get_book(bid) is None)
        check("书库总数还原", len(A.load_data()["books"]) == before_count,
              "%d → %d" % (before_count, len(A.load_data()["books"])))

    return finish(lib, backup, before_md5)


def finish(lib, backup, before_md5):
    """无条件还原书库并校验，保证零污染"""
    try:
        shutil.copy2(backup, lib)
        os.remove(backup)
    except Exception as e:                                   # pragma: no cover
        print("!! 还原书库失败：%r —— 请手动从 %s 恢复" % (e, backup))
        return 1
    restored = md5(lib) == before_md5
    check("测试后书库已完整还原（md5 一致）", restored)

    for name, ok, extra in RESULTS:
        print("%s - %s%s" % ("PASS" if ok else "FAIL", name,
                             ("  | " + extra) if extra else ""))
    fails = [n for n, ok, _ in RESULTS if not ok]
    print("=" * 60)
    print("TOTAL %d/%d" % (len(RESULTS) - len(fails), len(RESULTS)))
    if fails:
        print("失败项：")
        for n in fails:
            print("  - " + n)
        return 1
    print("全部通过 ✓（数据已零污染还原）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
