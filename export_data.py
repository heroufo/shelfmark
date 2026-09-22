# -*- coding: utf-8 -*-
"""
导出「在线只读浏览站」数据：从本地书库生成净化版 library.json + 复制封面。

两种调用方式：
1) 独立脚本（源码版，publish.bat 沿用）:
      python export_data.py <站点目录>
      <站点目录> 例如与项目同级的 library-web 仓库路径

2) 被 app.py import（打包版「在线发布」按钮直接调用，无需 python 子进程）:
      from export_data import export_to
      n_books, n_shelves, n_covers = export_to(site_dir, library_file, covers_dir)

输出:
     <站点目录>/data/library.json    (去掉 file_path 等本机路径，保留展示字段)
     <站点目录>/data/covers/*        (封面图片)
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

import json
import os
import shutil
import sys

# 导出的字段白名单（不包含 file_path 等本机路径，避免泄露）
EXPORT_FIELDS = [
    "book_id", "title", "subtitle", "author", "author_nationality",
    "series", "series_number",
    "publisher", "publish_year", "pages", "rating", "tags", "status",
    "cover_path", "blurb", "notes", "added_time",
]


def export_to(site_dir, library_file, covers_dir):
    """
    把本地书库 library_file（+ 封面目录 covers_dir）导出到站点目录 site_dir。
    返回 (n_books, n_shelves, n_covers) 三元组。
    站点目录或书库缺失时抛 FileNotFoundError。
    """
    if not os.path.isdir(site_dir):
        raise FileNotFoundError(f"站点目录不存在: {site_dir}")
    if not os.path.isfile(library_file):
        raise FileNotFoundError(f"找不到书库数据: {library_file}")

    with open(library_file, encoding="utf-8") as f:
        data = json.load(f)
    books = data.get("books", [])
    shelves = data.get("shelves", [])

    out_books = []
    for b in books:
        nb = {k: b.get(k) for k in EXPORT_FIELDS}
        # 封面统一转文件名（兼容绝对路径/相对路径）
        cp = nb.get("cover_path") or ""
        if cp and not cp.startswith(("http://", "https://")):
            nb["cover_path"] = os.path.basename(cp.replace("\\", "/"))
        out_books.append(nb)

    out = {"version": 1, "books": out_books, "shelves": shelves}
    out_data = os.path.join(site_dir, "data", "library.json")
    os.makedirs(os.path.dirname(out_data), exist_ok=True)
    with open(out_data, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 复制封面
    out_covers = os.path.join(site_dir, "data", "covers")
    os.makedirs(out_covers, exist_ok=True)
    copied = 0
    for b in out_books:
        cp = b.get("cover_path") or ""
        if not cp or cp.startswith(("http://", "https://")):
            continue
        src = os.path.join(covers_dir, cp)
        if os.path.isfile(src):
            dst = os.path.join(out_covers, cp)
            if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                shutil.copy2(src, dst)
            copied += 1

    return len(out_books), len(shelves), copied


def main():
    """CLI 入口：python export_data.py <站点目录>（默认用脚本同目录的 data/ 与 static/covers/）。"""
    if len(sys.argv) < 2:
        print("用法: python export_data.py <站点目录>")
        sys.exit(1)
    site_dir = sys.argv[1].strip().strip('"').strip("'")
    base = os.path.dirname(os.path.abspath(__file__))
    library_file = os.path.join(base, "data", "library.json")
    covers_dir = os.path.join(base, "static", "covers")
    try:
        n_books, n_shelves, copied = export_to(site_dir, library_file, covers_dir)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    print(f"导出完成: {n_books} 本书, {n_shelves} 个书架, 封面 {copied} 张")
    print(f"  -> {os.path.join(site_dir, 'data', 'library.json')}")
    print(f"  -> {os.path.join(site_dir, 'data', 'covers')}")


if __name__ == "__main__":
    main()
