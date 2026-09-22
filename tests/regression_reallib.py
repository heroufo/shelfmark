# -*- coding: utf-8 -*-
"""
重构回归脚本（针对真实书库跑全量路由与数据一致性检查）。

用途：代码结构调整（拆包、抽模块）后，快速确认「行为零变化」。
与 tests/test_*.py 的分工：本脚本面向本机真实书库，端到端跑全部页面；
单元测试面向隔离数据，可在没有 data/library.json 的环境（CI）运行。

用法：
    python tests/regression_reallib.py                # 跑全部检查
    python tests/regression_reallib.py --baseline X   # 指定基线书库做 md5 对比
退出码 0 = 全部通过，1 = 有失败项。
"""

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PUBLISH_DRY_RUN"] = "1"          # 发布走 dry-run，绝不碰 git

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=os.path.join(
        ROOT, "backup_pre_exe", "pre_p1_20260922", "data", "library.json"),
        help="用于 md5 对比的基线书库（默认取重构前备份）")
    args = ap.parse_args()

    import app as A

    client = A.app.test_client()
    data = A.load_data()
    books = data["books"]
    check("书库已加载", len(books) > 0, "%d 本" % len(books))
    if not books:
        report()
        return 1

    bid = books[0]["book_id"]
    shelves = data.get("shelves") or []
    sid = shelves[0].get("id") if shelves else None

    # ---- 1) 全部页面 GET ----
    urls = ["/", "/all", "/all?q=三体", "/all?sort=pages:desc",
            "/all?sort=added_time:asc&view=cards", "/all?status=已读",
            "/all?view=list", "/book/add", "/book/%s" % bid,
            "/book/edit/%s" % bid, "/stats", "/shelves", "/import",
            "/series", "/static/css/bootstrap.min.css",
            "/static/js/bootstrap.bundle.min.js",
            "/static/images/default_cover.svg",
            "/static/images/shelfmark_logo.png"]
    if sid:
        urls += ["/shelf/%s" % sid, "/shelf/%s/edit" % sid]
    author = next((b.get("author") for b in books if b.get("author")), None)
    if author:
        urls.append("/author/" + author)
    publisher = next((b.get("publisher") for b in books if b.get("publisher")), None)
    if publisher:
        urls.append("/publisher/" + publisher)

    for u in urls:
        r = client.get(u)
        check("GET %s" % u[:44], r.status_code == 200, str(r.status_code))

    # ---- 2) 页面内容断言 ----
    html = client.get("/").get_data(as_text=True)
    check("页面含品牌名", A.APP_NAME in html, A.APP_NAME)
    check("页面无旧品牌词", "霍格沃茨" not in html and "Hogwarts" not in html)
    check("页脚注入版本号", "v" + A.APP_VERSION in html, "v" + A.APP_VERSION)

    detail = client.get("/book/%s" % bid).get_data(as_text=True)
    check("详情页可渲染", len(detail) > 500, "%d 字节" % len(detail))
    check("详情页含封面引用",
          "/static/covers/" in detail or "default_cover.svg" in detail)

    # ---- 3) 数据零改动 ----
    lib = os.path.join(A.DATA_DIR, "library.json")
    if os.path.isfile(args.baseline):
        check("书库数据未被改动（md5）", md5(lib) == md5(args.baseline))
    else:
        check("书库数据未被改动（md5）", True, "无基线，跳过")

    # ---- 4) 模块边界与同源性 ----
    import shelfmark.paths as P
    import shelfmark.storage as S
    import shelfmark.utils as U
    check("app 与 storage 同源函数对象", A.load_data is S.load_data)
    check("app 与 utils 同源函数对象", A.safe_num is U.safe_num)
    check("DATA_DIR 指向项目 data/",
          os.path.normcase(P.DATA_DIR) == os.path.normcase(os.path.join(ROOT, "data")),
          P.DATA_DIR)
    check("未误建 shelfmark/data 目录",
          not os.path.isdir(os.path.join(ROOT, "shelfmark", "data")))
    check("站点目录推导正确",
          os.path.normcase(A.get_site_dir()) ==
          os.path.normcase(os.path.join(os.path.dirname(ROOT), "library-web")),
          A.get_site_dir())

    # ---- 5) 发布 dry-run（真实走导出逻辑，但不 push）----
    try:
        j = client.post("/publish").get_json()
        check("publish dry-run", j.get("ok") is True,
              json.dumps(j, ensure_ascii=False)[:120])
    except Exception as e:                                   # pragma: no cover
        check("publish dry-run", False, repr(e))

    # ---- 6) 清理测试产生的状态文件 ----
    for f in ("publish_state.json", "config.json"):
        p = os.path.join(A.DATA_DIR, f)
        try:
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass

    return report()


def report():
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
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
