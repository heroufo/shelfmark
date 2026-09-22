# -*- coding: utf-8 -*-
"""浏览类页面：主页、全部书籍、书籍详情、作者/出版社/丛书聚合视图。"""

import random
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from shelfmark.books import (
    LEGACY_SORT,
    SORTABLE_FIELDS,
    _ensure_shelves,
    recommend_related,
)
from shelfmark.metadata import fetch_book_blurb
from shelfmark.paths import PAGE_SIZE_CARDS, PAGE_SIZE_LIST, SHELF_COUNT
from shelfmark.storage import get_book, load_data, save_data
from shelfmark.utils import safe_num


def _index_impl(show_all=False):
    data = load_data()
    books = data["books"]

    # ---- 读取查询参数 ----
    q = request.args.get("q", "").strip()
    selected_tags = request.args.getlist("tag")                 # 标签可多选
    status = request.args.get("status", "").strip()
    rating = request.args.get("rating", "").strip()
    series = request.args.get("series", "").strip()
    view = request.args.get("view", "cards").strip() or "cards"

    # ---- 排序参数：复合格式「字段:方向」（兼容旧版 sort 值）----
    sort = request.args.get("sort", "").strip() or "added_time:desc"
    sort = LEGACY_SORT.get(sort, sort)
    if ":" in sort:
        sort_by, sort_dir = sort.split(":", 1)
    else:
        sort_by, sort_dir = sort, "desc"
    if sort_by not in SORTABLE_FIELDS:
        sort_by, sort_dir = "added_time", "desc"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    sort = f"{sort_by}:{sort_dir}"     # 规范化后的复合参数，回传给模板链接

    # ---- 搜索：书名 / 副标题 / 作者 / ISBN 模糊匹配（不区分大小写）----
    if q:
        ql = q.lower()
        # ISBN 搜索容错：忽略连字符与空格
        ql_isbn = ql.replace("-", "").replace(" ", "")
        books = [b for b in books
                 if ql in b.get("title", "").lower()
                 or ql in b.get("subtitle", "").lower()
                 or ql in b.get("author", "").lower()
                 or (ql_isbn and ql_isbn in
                     b.get("isbn", "").replace("-", "")
                     .replace(" ", "").lower())]

    # ---- 筛选：标签（任一命中）/ 状态 / 星级 / 丛书 ----
    if selected_tags:
        tag_set = set(selected_tags)
        books = [b for b in books if tag_set & set(b.get("tags", []))]
    if status:
        books = [b for b in books if b.get("status") == status]
    if rating == "none":
        books = [b for b in books if not b.get("rating")]
    elif rating.isdigit():
        books = [b for b in books if safe_num(b.get("rating")) == int(rating)]
    if series:
        books = [b for b in books if b.get("series") == series]

    # ---- 通用排序（字段 + 方向）----
    books.sort(key=SORTABLE_FIELDS[sort_by], reverse=(sort_dir == "desc"))

    # ---- 分页：表格视图每页 50 本，封面墙每页 54 本 ----
    per_page = PAGE_SIZE_LIST if view == "list" else PAGE_SIZE_CARDS
    total = len(books)
    total_pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_books = books[start:start + per_page]

    # ---- 筛选面板数据 ----
    all_tags = sorted({t for b in data["books"] for t in b.get("tags", [])})
    all_series = sorted({b.get("series") for b in data["books"]
                         if b.get("series")})

    # ---- 封面墙分栏数据（基于全量书库，无筛选条件时展示）----
    all_books = data["books"]
    recent_books = sorted(all_books, key=lambda b: b.get("added_time", ""),
                          reverse=True)[:SHELF_COUNT]
    recent_ids = {rb["book_id"] for rb in recent_books}
    pool = [b for b in all_books if b["book_id"] not in recent_ids]
    random_books = (random.sample(pool, min(SHELF_COUNT, len(pool)))
                    if pool else [])

    return render_template(
        "index.html",
        books=books,
        page_books=page_books,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        total=len(data["books"]),
        filtered_count=total,
        all_tags=all_tags,
        all_series=all_series,
        q=q,
        selected_tags=selected_tags,
        status=status,
        rating=rating,
        series=series,
        sort=sort,
        sort_by=sort_by,
        sort_dir=sort_dir,
        view=view,
        recent_books=recent_books,
        random_books=random_books,
        show_all=show_all,
        normal_shelves=[s for s in _ensure_shelves(data)
                        if s.get("kind") != "smart"],
    )


def index():
    """首页：最近添加 + 随机发现（封面墙）或筛选结果。"""
    return _index_impl(show_all=False)


def all_books():
    """全部书籍独立页：完整列表（封面墙 / 表格），分页展示。"""
    return _index_impl(show_all=True)


def book_detail(book_id):
    """书籍详情页（含相关书籍推荐，简介自动补全）。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    data = load_data()
    # 首次访问且尚无网络简介时，自动从豆瓣获取（成功后写回库，避免重复请求）
    dirty = False
    if not book.get("blurb"):
        blurb = fetch_book_blurb(book.get("title"),
                                book.get("author"), book.get("isbn"))
        if blurb:
            book["blurb"] = blurb
            dirty = True
    if dirty:
        for i, b in enumerate(data["books"]):
            if b["book_id"] == book_id:
                data["books"][i] = book
                break
        save_data(data)
    related_books = recommend_related(book, data["books"])
    all_shelves = data.get("shelves", [])
    normal_shelves = [s for s in all_shelves if s.get("kind") != "smart"]
    book_shelves = [s for s in normal_shelves if book_id in s.get("book_ids", [])]
    book_shelf_ids = {s["id"] for s in book_shelves}
    addable_shelves = [s for s in normal_shelves if s["id"] not in book_shelf_ids]
    # 翻书导航：按主页默认排序（入库时间 新→旧）定位当前书，取前后相邻
    sorted_books = sorted(data["books"],
                          key=SORTABLE_FIELDS["added_time"], reverse=True)
    total_books = len(sorted_books)
    pos = next((i for i, b in enumerate(sorted_books)
                if b["book_id"] == book_id), -1)
    prev_book = sorted_books[pos - 1] if pos > 0 else None
    next_book = sorted_books[pos + 1] if 0 <= pos < total_books - 1 else None
    return render_template("book_detail.html", book=book,
                           related_books=related_books,
                           normal_shelves=normal_shelves,
                           book_shelves=book_shelves,
                           addable_shelves=addable_shelves,
                           prev_book=prev_book,
                           next_book=next_book,
                           current_pos=(pos + 1 if pos >= 0 else 0),
                           total_books=total_books)


def author_view(author):
    """作者页：列出该作者的全部书籍（封面墙 + 分页）。"""
    data = load_data()
    books = [b for b in data["books"] if b.get("author") == author]
    books.sort(key=lambda b: (b.get("title") or "").lower())
    per_page = PAGE_SIZE_CARDS
    total = len(books)
    total_pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_books = books[start:start + per_page]
    return render_template("author.html", author=author,
                           page_books=page_books, page=page,
                           total_pages=total_pages, per_page=per_page,
                           total=total)


def publisher_view(publisher):
    """出版社页：列出该出版社的全部书籍（封面墙 + 分页）。"""
    data = load_data()
    books = [b for b in data["books"] if b.get("publisher") == publisher]
    books.sort(key=lambda b: (b.get("title") or "").lower())
    per_page = PAGE_SIZE_CARDS
    total = len(books)
    total_pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_books = books[start:start + per_page]
    return render_template("publisher.html", publisher=publisher,
                           page_books=page_books, page=page,
                           total_pages=total_pages, per_page=per_page,
                           total=total)


def series_view():
    """
    丛书页：按丛书分组展示，同丛书内按卷号升序。
    通过 ?name=丛书名 筛选查看指定丛书全部分卷。
    """
    data = load_data()
    selected = request.args.get("name", "").strip()

    groups = {}
    for b in data["books"]:
        name = b.get("series") or "未分类"
        groups.setdefault(name, []).append(b)
    for name in groups:
        groups[name].sort(key=lambda b: safe_num(b.get("series_number"),
                                                 10 ** 9))

    # 当前要展示的书籍列表
    if selected:
        books = groups.get(selected, [])
    else:
        books = []
        for name in sorted(groups):
            books.extend(groups[name])

    return render_template("series.html", groups=groups,
                           selected=selected, books=books)


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.add_url_rule('/', 'index', index)
    app.add_url_rule('/all', 'all_books', all_books)
    app.add_url_rule('/book/<book_id>', 'book_detail', book_detail)
    app.add_url_rule('/author/<path:author>', 'author_view', author_view)
    app.add_url_rule('/publisher/<path:publisher>', 'publisher_view', publisher_view)
    app.add_url_rule('/series', 'series_view', series_view)
