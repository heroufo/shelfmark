# -*- coding: utf-8 -*-
"""书籍领域逻辑：排序配置、相似推荐、表单校验与构建、封面地址、
书架规则与标签统计。
本模块不含路由，视图层与测试都直接调用这里的函数。"""

import os
from flask import url_for

from shelfmark.nationality import nationality_from_filename
from shelfmark.paths import BASE_DIR, COVER_UPLOAD_DIR
from shelfmark.utils import guess_format, normalize_tags, safe_num


SORTABLE_FIELDS = {
    "title": lambda b: (b.get("title") or "").lower(),
    "author": lambda b: (b.get("author") or "").lower(),
    "series": lambda b: ((b.get("series") or "").lower(),
                         safe_num(b.get("series_number"), 10 ** 9)),
    "publisher": lambda b: (b.get("publisher") or "").lower(),
    "publish_year": lambda b: safe_num(b.get("publish_year")),
    "rating": lambda b: safe_num(b.get("rating")),
    "pages": lambda b: safe_num(b.get("pages")),
    "status": lambda b: b.get("status") or "",
    "file_format": lambda b: (b.get("file_format") or "").lower(),
    "added_time": lambda b: b.get("added_time") or "",
}


LEGACY_SORT = {
    "added_desc": "added_time:desc",
    "added_asc": "added_time:asc",
    "series_number": "series:asc",
    "rating_desc": "rating:desc",
}


def recommend_related(book, books, limit=9):
    """
    相关书籍推荐（基于内容 Content-Based 的加权相似度算法，纯 Python 实现）：
    参考业界主流做法——用书籍元数据特征构建相似度，而非依赖用户行为
    （协同过滤需要大量用户评分数据，本地单用户场景不适用）。

    特征权重：
    - 标签 Jaccard 相似度  |交集|/|并集|  权重 3.0（最核心特征）
    - 丛书相同（同丛书分卷强相关）        权重 3.0
    - 作者相同                           权重 2.0
    - 出版社相同                         权重 1.0
    - 出版年相差 ≤ 2 年                   权重 0.5
    - 评分相同（弱信号）                  权重 0.3

    完全无关（总分 = 0）的书不参与推荐；返回前 limit 本。
    """
    def score(other):
        s = 0.0
        tags_a = set(book.get("tags") or [])
        tags_b = set(other.get("tags") or [])
        if tags_a and tags_b:
            s += 3.0 * len(tags_a & tags_b) / len(tags_a | tags_b)
        if book.get("series") and book.get("series") == other.get("series"):
            s += 3.0
        if book.get("author") and book.get("author") == other.get("author"):
            s += 2.0
        if (book.get("publisher")
                and book.get("publisher") == other.get("publisher")):
            s += 1.0
        ya = safe_num(book.get("publish_year"))
        yb = safe_num(other.get("publish_year"))
        if ya and yb and abs(ya - yb) <= 2:
            s += 0.5
        if book.get("rating") and book.get("rating") == other.get("rating"):
            s += 0.3
        return s

    scored = [(score(b), b) for b in books
              if b["book_id"] != book["book_id"]]
    scored = [(s, b) for s, b in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in scored[:limit]]


def validate_book_form(form):
    """
    表单校验：
    - 书名必填
    - 卷号若填写必须是数字
    - 出版年若填写必须是 4 位数字
    返回错误信息字符串，通过校验返回 None。
    """
    if not form.get("title", "").strip():
        return "书名不能为空"
    sn = form.get("series_number", "").strip()
    if sn and not sn.isdigit():
        return "卷号必须是数字（例如：1、2、3）"
    py = form.get("publish_year", "").strip()
    if py and (not py.isdigit() or len(py) != 4):
        return "出版年必须是 4 位数字（例如：2020）"
    return None


def build_book_from_form(form):
    """把表单数据整理成一条书籍记录（不含 book_id / added_time）。"""
    sn_str = form.get("series_number", "").strip()
    py_str = form.get("publish_year", "").strip()
    return {
        "title": form.get("title", "").strip(),
        "subtitle": form.get("subtitle", "").strip(),
        "author": form.get("author", "").strip(),
        "author_nationality": (form.get("author_nationality", "").strip()
                               or nationality_from_filename(
                                   form.get("file_path", ""))),
        "series": form.get("series", "").strip(),
        "series_number": safe_num(sn_str) if sn_str else 0,
        "publisher": form.get("publisher", "").strip(),
        "publish_year": safe_num(py_str) if py_str else 0,
        "pages": safe_num(form.get("pages", "0"), 0),
        "isbn": form.get("isbn", "").strip(),
        "file_path": form.get("file_path", "").strip(),
        "file_format": form.get("file_format", "").strip()
                      or guess_format(form.get("file_path", "")),
        "cover_path": form.get("cover_path", "").strip(),
        "rating": safe_num(form.get("rating", "0"), 0),
        "tags": normalize_tags(form.get("tags", "")),
        "status": form.get("status", "").strip() or "未读",
        "notes": form.get("notes", "").strip(),
    }


def form_values_from(book=None, form=None):
    """生成 book_form.html 需要回填的字段字典（新增 / 编辑 / 校验失败共用）。"""
    src = form if form is not None else (book or {})
    vals = {}
    for key in ["title", "subtitle", "author", "author_nationality", "series",
                "publisher", "isbn",
                "file_path", "file_format", "cover_path",
                "status", "notes"]:
        vals[key] = src.get(key, "") if src else ""
    # 出版年存的是数字（0 表示未知），回填时转字符串
    vals["publish_year"] = str(src.get("publish_year", "")) if (src and src.get("publish_year")) else ""
    vals["pages"] = str(src.get("pages", "")) if (src and src.get("pages")) else ""
    vals["rating"] = str(src.get("rating", 0)) if src else "0"
    vals["series_number"] = str(src.get("series_number", "")) if src else ""
    if form is not None:
        vals["tags_str"] = form.get("tags", "")
    else:
        vals["tags_str"] = ", ".join((book or {}).get("tags", []))
    return vals


def cover_url(book):
    """
    返回书籍封面可访问 URL：优先真实封面，缺失时回退内置占位图。
    兼容性（换电脑可移植）：cover_path 可能是
      - http(s) 外链
      - 仅文件名（如 cover_xxx.jpg）或相对路径 covers/xxx.jpg
      - 旧数据的本机绝对路径
    统一提取文件名，若 static/covers 下存在则走静态路由（与机器路径无关）。
    """
    path = (book or {}).get("cover_path", "")
    if not path:
        return url_for("static", filename="images/default_cover.svg")
    if path.startswith(("http://", "https://")):
        return path
    # 统一提取文件名（兼容绝对 / 相对 / 纯文件名，Windows/Unix 分隔符）
    basename = os.path.basename(path.replace("\\", "/"))
    if basename:
        candidate = os.path.join(COVER_UPLOAD_DIR, basename)
        if os.path.isfile(candidate):
            return url_for("static", filename="covers/" + basename)
    # 兼容：旧数据绝对路径仍可用（本机）
    if os.path.isfile(path):
        covers_prefix = os.path.abspath(COVER_UPLOAD_DIR) + os.sep
        if os.path.abspath(path).startswith(covers_prefix):
            rel = os.path.relpath(path, os.path.join(BASE_DIR, "static"))
            return url_for("static", filename=rel.replace(os.sep, "/"))
        return url_for("serve_file", filepath=path)
    return url_for("static", filename="images/default_cover.svg")


def _tag_stats(data):
    """标签统计数据（供「工具合集」页展示）：按数量降序。"""
    counts = {}
    for b in data["books"]:
        for t in b.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return {"top": top, "total_tags": len(top),
            "total_books": len(data["books"]),
            "max_count": (top[0][1] if top else 1)}


def _ensure_shelves(data):
    """确保 data 含 shelves 键（兼容旧库）。"""
    return data.setdefault("shelves", [])


def shelf_members(shelf, books):
    """返回书架内的书籍列表（普通=按 book_ids 顺序；智能=按规则实时筛选）。"""
    if shelf.get("kind") == "smart":
        rule = shelf.get("rule") or {}
        tags = set(rule.get("tags") or [])
        status = (rule.get("status") or "").strip()
        author = (rule.get("author") or "").strip()
        series = (rule.get("series") or "").strip()
        rating = safe_num(rule.get("rating"), 0)
        out = []
        for b in books:
            if tags and not (tags & set(b.get("tags", []))):
                continue
            if status and b.get("status") != status:
                continue
            if author and (b.get("author") or "") != author:
                continue
            if series and (b.get("series") or "") != series:
                continue
            if rating and safe_num(b.get("rating")) != rating:
                continue
            out.append(b)
        return out
    by_id = {b["book_id"]: b for b in books}
    return [by_id[i] for i in shelf.get("book_ids", []) if i in by_id]


def shelf_rule_text(shelf):
    """把智能书架规则转成可读中文描述。"""
    rule = shelf.get("rule") or {}
    parts = []
    if rule.get("tags"):
        parts.append("标签含 " + "、".join(rule["tags"]))
    if rule.get("status"):
        parts.append("状态=" + rule["status"])
    if rule.get("author"):
        parts.append("作者=" + rule["author"])
    if rule.get("series"):
        parts.append("丛书=" + rule["series"])
    if safe_num(rule.get("rating"), 0):
        parts.append("评分≥" + str(rule["rating"]))
    return " 且 ".join(parts) if parts else "（空规则，暂不含任何书）"
