# -*- coding: utf-8 -*-
"""
网页版本地电子书管理器 —— Flask 后端主程序

功能概览：
- 书库元数据 JSON 持久化（启动自动加载，缺失/损坏自动重建）
- 书籍增删改查（删除仅移除元数据记录，绝不删除磁盘文件）
- 批量扫描导入本地文件夹中的 pdf / epub / mobi
- 表格列表 / 封面卡片 双视图切换
- 丛书分组与分卷浏览（同丛书按卷号升序）
- 搜索、多维筛选（标签/状态/星级/丛书）、排序（入库时间/卷号/评分）
- 调用系统默认程序打开书籍文件（Windows / macOS / Linux）
- 书库元数据导出为 JSON 下载
- 异常校验：无效路径、卷号非数字等均捕获并友好提示，不崩溃
"""

import json
import os
import platform
import random
import re
import shutil
import ssl
import sys
import urllib.parse
import urllib.request
import subprocess
import tempfile
import uuid
import time
from datetime import datetime

from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, send_file,
                   send_from_directory, url_for)

# 本地模块：在线发布数据导出（打包版以 import 方式调用，避免依赖 python 子进程）
import export_data

# ---------------------------------------------------------------------------
# 项目内模块
# 拆分后的内部模块（行为与原单文件实现完全一致）
# ---------------------------------------------------------------------------
from shelfmark.books import (
    LEGACY_SORT,
    SORTABLE_FIELDS,
    _ensure_shelves,
    _tag_stats,
    build_book_from_form,
    cover_url,
    form_values_from,
    recommend_related,
    shelf_members,
    shelf_rule_text,
    validate_book_form,
)
from shelfmark.dialogs import (
    open_file_with_default_app,
    pick_file_dialog,
    pick_folder_dialog,
)
from shelfmark.metadata import (
    _fetch_meta_by_title,
    fetch_book_blurb,
    fetch_book_meta,
    refresh_book_blurb,
)
from shelfmark.nationality import _nat_stats, nationality_from_filename
from shelfmark.publishing import (
    _diff_books,
    _read_publish_state,
    _save_publish_state,
)

# ---------------------------------------------------------------------------
# 项目内模块
# 拆分后的内部模块（行为与原单文件实现完全一致）
# ---------------------------------------------------------------------------
from shelfmark.paths import (
    ALLOWED_COVER_EXT,
    ALLOWED_FORMATS,
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    COVER_UPLOAD_DIR,
    DATA_DIR,
    FORMAT_OPTIONS,
    IS_FROZEN,
    LIBRARY_FILE,
    MAX_COVER_SIZE,
    PAGE_SIZE_CARDS,
    PAGE_SIZE_LIST,
    PUBLISH_STATE_FILE,
    RATING_OPTIONS,
    RUNTIME_DIR,
    SHELF_COUNT,
    STATUS_OPTIONS,
)
from shelfmark.storage import (
    ensure_data_dir,
    get_book,
    get_site_dir,
    load_data,
    online_metadata_enabled,
    save_data,
)
from shelfmark.utils import (
    _strip_html,
    _truncate_cn,
    file_exists,
    guess_format,
    normalize_tags,
    now_str,
    safe_num,
    status_class,
    title_from_filename,
)


# ---------------------------------------------------------------------------
# 网络简介获取（详情页「简介」自动补全，数据源：豆瓣）
# ---------------------------------------------------------------------------


app = Flask(__name__)
# 本地单用户工具，密钥仅用于 flash 消息签名
app.secret_key = "ebook-manager-local-secret-key"


# ---------------------------------------------------------------------------
# 数据持久化
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Jinja 全局辅助（供模板直接调用）
# ---------------------------------------------------------------------------


app.jinja_env.globals["cover_url"] = cover_url
app.jinja_env.globals["status_class"] = status_class
app.jinja_env.globals["file_exists"] = file_exists


@app.context_processor
def inject_library_stats():
    """为所有模板注入书库统计（侧边栏 / 底部状态栏使用）。"""
    data = load_data()
    books = data["books"]
    return {
        "lib_total": len(books),
        "lib_status_counts": {
            s: sum(1 for b in books if b.get("status") == s)
            for s in STATUS_OPTIONS
        },
        "app_version": APP_VERSION,
        "app_name": APP_NAME,
    }


@app.context_processor
def inject_nav_shelves():
    """为所有模板注入书架列表（侧边栏「书架」分组动态展示已创建内容）。"""
    data = load_data()
    shelves = _ensure_shelves(data)
    return {
        "nav_shelves": [
            {"id": s["id"], "name": s.get("name", ""), "kind": s.get("kind", "normal")}
            for s in shelves
        ],
    }


# ---------------------------------------------------------------------------
# 静态文件服务（用于加载本机磁盘上的封面图片）
# ---------------------------------------------------------------------------

@app.route("/file/<path:filepath>")
def serve_file(filepath):
    """按本地绝对路径返回文件内容（本工具为本地单用户工具）。"""
    if os.path.isfile(filepath):
        return send_file(filepath)
    abort(404)


if IS_FROZEN:
    # 打包版封面外置在 exe 旁 covers/ 目录；本路由把 /static/covers/<名> 转发过去。
    # 规则比 Flask 默认 /static/<path> 更具体，会优先命中；缺图回退内置占位图。
    @app.route("/static/covers/<path:filename>")
    def covers_external(filename):
        safe = os.path.basename(filename.replace("\\", "/"))
        if safe and os.path.isfile(os.path.join(COVER_UPLOAD_DIR, safe)):
            return send_from_directory(COVER_UPLOAD_DIR, safe)
        return redirect(url_for("static", filename="images/default_cover.svg"))


@app.route("/api/browse_file")
def api_browse_file():
    """
    弹出系统原生「选择文件」对话框，返回选中的文件路径（JSON）。
    前端「浏览…」按钮通过 fetch 调用本接口并回填到文件路径输入框。
    """
    try:
        path = pick_file_dialog()
    except Exception as e:
        return jsonify({"ok": False, "message": f"打开文件选择器失败：{e}"})
    if path:
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False, "message": "未选择文件或已取消"})


@app.route("/api/browse_folder")
def api_browse_folder():
    """
    弹出系统原生「选择目录」对话框（批量导入用），返回选中的文件夹路径（JSON）。
    """
    try:
        path = pick_folder_dialog()
    except Exception as e:
        return jsonify({"ok": False, "message": f"打开目录选择器失败：{e}"})
    if path:
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False, "message": "未选择目录或已取消"})


@app.route("/api/book_meta")
def api_book_meta():
    """
    按 ISBN 从豆瓣查询书名 / 作者 / 出版社 / 出版年（JSON）。
    纯查询不写库；失败返回 ok=False 与提示，由前端回填或提示。
    """
    isbn = request.args.get("isbn", "").strip()
    if not isbn:
        return jsonify({"ok": False, "message": "请先填写 ISBN 再查询"})
    meta = fetch_book_meta(isbn)
    if not meta:
        return jsonify({"ok": False,
                        "message": "未能在豆瓣查到该书（请检查 ISBN；若此前正常，"
                                   "可能是豆瓣临时限制访问，稍等片刻再试）"})
    return jsonify({"ok": True, **meta})


@app.route("/api/upload_cover", methods=["POST"])
def api_upload_cover():
    """
    接收封面图片上传，保存到 static/covers/ 并返回可存入 cover_path 的文件名（相对 static/covers，可移植）。
    - 仅允许常见图片格式，单张最大 5MB
    - 文件名由服务端生成（uuid），不使用客户端文件名，避免路径注入
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "message": "未收到图片文件"})

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_COVER_EXT:
        return jsonify({"ok": False,
                        "message": f"不支持的图片格式：{ext or '未知'}"
                                   f"（支持 png / jpg / jpeg / gif / webp / svg / bmp）"})

    # 大小限制
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > MAX_COVER_SIZE:
        return jsonify({"ok": False,
                        "message": "图片过大，请上传小于 5MB 的图片"})

    try:
        os.makedirs(COVER_UPLOAD_DIR, exist_ok=True)
        filename = f"cover_{uuid.uuid4().hex[:12]}{ext}"
        save_path = os.path.join(COVER_UPLOAD_DIR, filename)
        f.save(save_path)
    except Exception as e:
        return jsonify({"ok": False, "message": f"保存图片失败：{e}"})

    return jsonify({"ok": True, "path": filename, "message": "上传成功"})


# ---------------------------------------------------------------------------
# 书库主页：搜索 / 筛选 / 排序 / 视图切换
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """首页：最近添加 + 随机发现（封面墙）或筛选结果。"""
    return _index_impl(show_all=False)


@app.route("/all")
def all_books():
    """全部书籍独立页：完整列表（封面墙 / 表格），分页展示。"""
    return _index_impl(show_all=True)


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


# ---------------------------------------------------------------------------
# 新增 / 编辑 / 详情 / 删除
# ---------------------------------------------------------------------------

@app.route("/book/add", methods=["GET", "POST"])
def book_add():
    """新增书籍：GET 渲染表单，POST 校验并入库。"""
    if request.method == "POST":
        err = validate_book_form(request.form)
        if err:
            flash(err, "danger")
            return render_template(
                "book_form.html", is_edit=False, book=None,
                vals=form_values_from(form=request.form),
                status_options=STATUS_OPTIONS,
                rating_options=RATING_OPTIONS,
                format_options=FORMAT_OPTIONS,
            )
        book = build_book_from_form(request.form)
        book["book_id"] = uuid.uuid4().hex
        book["added_time"] = now_str()
        data = load_data()
        data["books"].append(book)
        save_data(data)
        flash(f"《{book['title']}》已加入书库", "success")
        return redirect(url_for("book_detail", book_id=book["book_id"]))

    return render_template(
        "book_form.html", is_edit=False, book=None,
        vals=form_values_from(),
        status_options=STATUS_OPTIONS,
        rating_options=RATING_OPTIONS,
        format_options=FORMAT_OPTIONS,
    )


@app.route("/book/edit/<book_id>", methods=["GET", "POST"])
def book_edit(book_id):
    """编辑书籍：完整修改全部元数据，book_id / added_time 保持不变。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        err = validate_book_form(request.form)
        if err:
            flash(err, "danger")
            return render_template(
                "book_form.html", is_edit=True, book=book,
                vals=form_values_from(form=request.form),
                status_options=STATUS_OPTIONS,
                rating_options=RATING_OPTIONS,
                format_options=FORMAT_OPTIONS,
            )
        new_values = build_book_from_form(request.form)
        for key, value in new_values.items():
            book[key] = value
        data = load_data()
        for i, b in enumerate(data["books"]):
            if b["book_id"] == book_id:
                data["books"][i] = book
                break
        save_data(data)
        flash(f"《{book['title']}》已更新", "success")
        return redirect(url_for("book_detail", book_id=book_id))

    return render_template(
        "book_form.html", is_edit=True, book=book,
        vals=form_values_from(book=book),
        status_options=STATUS_OPTIONS,
        rating_options=RATING_OPTIONS,
        format_options=FORMAT_OPTIONS,
    )


@app.route("/book/<book_id>/douban_update", methods=["POST"])
def book_douban_update(book_id):
    """
    详情页「豆瓣更新」：抓取豆瓣补齐空字段并直接保存（无需进入编辑页）。
    - 有 ISBN 用 ISBN 查询；无 ISBN 用书名搜索兜底
    - 只补全 作者/国籍/出版社/出版年/页数 的空值，不覆盖已有内容
    """
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    isbn = (book.get("isbn") or "").strip()
    meta = fetch_book_meta(isbn) if isbn else _fetch_meta_by_title(
        book.get("title"))
    if not meta:
        flash("豆瓣查询失败（未找到该书，或豆瓣临时限制访问，请稍后再试）",
              "danger")
        return redirect(request.referrer
                        or url_for("book_detail", book_id=book_id))
    labels = {"author": "作者", "author_nationality": "作者国籍",
              "publisher": "出版社", "publish_year": "出版年", "pages": "页数"}
    updated = []
    for f in labels:
        v = meta.get(f)
        if not v:
            continue
        if f == "pages":
            v = safe_num(str(v))
            if not v:
                continue
        else:
            v = str(v).strip()
            if not v:
                continue
        if not book.get(f):
            book[f] = v
            updated.append(labels[f])
    data = load_data()
    for i, b in enumerate(data["books"]):
        if b["book_id"] == book_id:
            data["books"][i] = book
            break
    save_data(data)
    if updated:
        flash(f"豆瓣更新成功：已补全「{', '.join(updated)}」", "success")
    else:
        flash("豆瓣更新完成：字段已是最新，无需补全", "info")
    return redirect(request.referrer
                    or url_for("book_detail", book_id=book_id))


@app.route("/book/<book_id>")
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


@app.route("/book/<book_id>/refresh_blurb")
def refresh_blurb(book_id):
    """手动重新获取简介（网络偶发失败时可重试，不影响已有内容）。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    blurb = refresh_book_blurb(book_id)
    if blurb:
        flash("已更新简介", "success")
    else:
        flash("本次未能从网络获取简介，可稍后重试（不影响已有内容）", "warning")
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/author/<path:author>")
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


@app.route("/publisher/<path:publisher>")
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


# ---------------------------------------------------------------------------
# 统计仪表盘（纯读 library.json，无写入）
# ---------------------------------------------------------------------------

@app.route("/stats")
def stats_view():
    """统计仪表盘：藏书总量、状态/星级/标签/作者/出版社分布、出版年趋势等。"""
    data = load_data()
    books = data["books"]
    total = len(books)
    status_counts = {s: sum(1 for b in books if b.get("status") == s)
                     for s in STATUS_OPTIONS}
    rating_counts = {r: sum(1 for b in books if safe_num(b.get("rating")) == r)
                     for r in RATING_OPTIONS}
    tag_counts, author_counts, publisher_counts = {}, {}, {}
    for b in books:
        for t in (b.get("tags") or []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
        if b.get("author"):
            author_counts[b["author"]] = author_counts.get(b["author"], 0) + 1
        if b.get("publisher"):
            publisher_counts[b["publisher"]] = \
                publisher_counts.get(b["publisher"], 0) + 1
    tag_top = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))[:10]
    author_top = sorted(author_counts.items(), key=lambda x: (-x[1], x[0]))[:10]
    publisher_top = sorted(publisher_counts.items(),
                           key=lambda x: (-x[1], x[0]))[:10]
    year_counts = {}
    for b in books:
        y = safe_num(b.get("publish_year"), 0)
        if y:
            year_counts[y] = year_counts.get(y, 0) + 1
    year_trend = sorted(year_counts.items())
    with_cover = sum(1 for b in books if b.get("cover_path"))
    with_blurb = sum(1 for b in books if b.get("blurb"))
    return render_template("stats.html",
        total=total, status_counts=status_counts, rating_counts=rating_counts,
        tag_top=tag_top, author_top=author_top, publisher_top=publisher_top,
        year_trend=year_trend,
        with_cover=with_cover, with_blurb=with_blurb)


# ---------------------------------------------------------------------------
# 智能书架 / 收藏书架
#   - 普通书架（kind=normal）：手动把书加入 book_ids
#   - 智能书架（kind=smart）：按 rule 规则实时筛选全部书籍
# ---------------------------------------------------------------------------


# 把后端函数/常量注册为 Jinja 模板全局（模板中可直接调用）
app.jinja_env.globals["shelf_rule_text"] = shelf_rule_text
app.jinja_env.globals["RATING_OPTIONS"] = RATING_OPTIONS


@app.route("/shelves")
def shelves_view():
    """书架列表：我的书架（手动）+ 智能书架（规则），含数量与新建表单。"""
    data = load_data()
    shelves = _ensure_shelves(data)
    books = data["books"]
    enriched = [(sh, len(shelf_members(sh, books))) for sh in shelves]
    normal = [(sh, c) for sh, c in enriched if sh.get("kind") != "smart"]
    smart = [(sh, c) for sh, c in enriched if sh.get("kind") == "smart"]
    return render_template("shelves.html", normal=normal, smart=smart,
                           status_options=STATUS_OPTIONS,
                           kind=request.args.get("kind", "").strip())


@app.route("/shelf/<shelf_id>")
def shelf_detail(shelf_id):
    """书架详情：列出该书架内的书籍；普通书架可逐本移除。"""
    data = load_data()
    shelf = next((s for s in _ensure_shelves(data) if s["id"] == shelf_id), None)
    if not shelf:
        flash("书架不存在", "danger")
        return redirect(url_for("shelves_view"))
    books = shelf_members(shelf, data["books"])
    return render_template("shelf_detail.html", shelf=shelf, books=books,
                           rule_text=shelf_rule_text(shelf))


@app.route("/shelf/create", methods=["POST"])
def shelf_create():
    """新建书架：手动（normal）或智能（smart，带 rule 规则）。"""
    name = request.form.get("name", "").strip()
    kind = "smart" if request.form.get("kind", "").strip() == "smart" else "normal"
    if not name:
        flash("请输入书架名称", "warning")
        return redirect(url_for("shelves_view"))
    data = load_data()
    shelves = _ensure_shelves(data)
    shelf = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "kind": kind,
        "book_ids": [],
        "rule": {},
        "created_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if kind == "smart":
        shelf["rule"] = {
            "tags": normalize_tags(request.form.get("rule_tags", "")),
            "status": request.form.get("rule_status", "").strip(),
            "author": request.form.get("rule_author", "").strip(),
            "series": request.form.get("rule_series", "").strip(),
            "rating": safe_num(request.form.get("rule_rating"), 0),
        }
    shelves.append(shelf)
    save_data(data)
    flash(f"已创建{'智能' if kind == 'smart' else ''}书架《{name}》", "success")
    return redirect(url_for("shelves_view", kind=kind))


@app.route("/shelf/add", methods=["POST"])
def shelf_add_book():
    """把一本书加入一个或多个「手动」书架（多选；智能书架不可手动加入）。"""
    shelf_ids = request.form.getlist("shelf_id") or request.form.getlist("s")
    shelf_ids = [s.strip() for s in shelf_ids if s.strip()]
    book_id = request.form.get("book_id", "").strip()
    if not shelf_ids or not book_id:
        flash("请至少选择一个书架", "warning")
        return redirect(url_for("book_detail", book_id=book_id))
    data = load_data()
    added, skipped = [], []
    for shelf_id in shelf_ids:
        shelf = next((s for s in _ensure_shelves(data) if s["id"] == shelf_id), None)
        if not shelf:
            continue
        if shelf.get("kind") == "smart":
            skipped.append(shelf.get("name", "智能书架"))
            continue
        ids = shelf.setdefault("book_ids", [])
        if book_id not in ids:
            ids.append(book_id)
            added.append(shelf.get("name", ""))
        else:
            skipped.append(shelf.get("name", ""))
    if added or skipped:
        save_data(data)
    if added:
        flash(f"已加入：{'、'.join(added)}", "success")
    if skipped:
        flash(f"已跳过（智能书架不可手动加入或已在书架中）：{'、'.join(skipped)}", "info")
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/shelf/<shelf_id>/remove", methods=["POST"])
def shelf_remove_book(shelf_id):
    """从手动书架移除一本书（支持从详情页返回）。"""
    book_id = request.form.get("book_id", "").strip()
    data = load_data()
    shelf = next((s for s in _ensure_shelves(data) if s["id"] == shelf_id), None)
    if shelf:
        shelf["book_ids"] = [i for i in shelf.get("book_ids", []) if i != book_id]
        save_data(data)
        flash("已从书架移除", "success")
    if request.form.get("next") == "book_detail" and book_id:
        return redirect(url_for("book_detail", book_id=book_id))
    return redirect(url_for("shelf_detail", shelf_id=shelf_id))


@app.route("/shelf/<shelf_id>/delete", methods=["POST"])
def shelf_delete(shelf_id):
    """删除书架（仅删书架与成员关系，不动书籍记录与磁盘文件）。"""
    data = load_data()
    shelves = _ensure_shelves(data)
    name = next((s.get("name") for s in shelves if s["id"] == shelf_id), "")
    data["shelves"] = [s for s in shelves if s["id"] != shelf_id]
    save_data(data)
    flash(f"已删除书架《{name}》", "success")
    return redirect(url_for("shelves_view"))


@app.route("/shelf/<shelf_id>/edit", methods=["GET", "POST"])
def shelf_edit(shelf_id):
    """编辑书架：展示预填表单（名称 / 智能规则），保存时更新名称与规则。"""
    data = load_data()
    shelf = next((s for s in _ensure_shelves(data) if s["id"] == shelf_id), None)
    if not shelf:
        flash("书架不存在", "danger")
        return redirect(url_for("shelves_view"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("书架名称不能为空", "warning")
            return redirect(url_for("shelf_edit", shelf_id=shelf_id))
        shelf["name"] = name
        if shelf.get("kind") == "smart":
            shelf["rule"] = {
                "tags": normalize_tags(request.form.get("rule_tags", "")),
                "status": request.form.get("rule_status", "").strip(),
                "author": request.form.get("rule_author", "").strip(),
                "series": request.form.get("rule_series", "").strip(),
                "rating": safe_num(request.form.get("rule_rating"), 0),
            }
        save_data(data)
        flash(f"已更新书架《{name}》", "success")
        return redirect(url_for("shelf_detail", shelf_id=shelf_id))
    return render_template("shelf_edit.html", shelf=shelf,
                           status_options=STATUS_OPTIONS)


@app.route("/book/delete/<book_id>", methods=["POST"])
def book_delete(book_id):
    """删除书籍：仅移除库中的元数据记录，绝不删除磁盘文件。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    data = load_data()
    data["books"] = [b for b in data["books"] if b["book_id"] != book_id]
    for sh in data.get("shelves", []):
        sh["book_ids"] = [i for i in sh.get("book_ids", []) if i != book_id]
    save_data(data)
    flash(f"已删除《{book['title']}》（仅删除记录，磁盘文件未动）", "success")
    return redirect(url_for("index"))


@app.route("/book/bulk_delete", methods=["POST"])
def book_bulk_delete():
    """
    批量删除书籍：接收多个 book_ids（表单多值），
    仅移除库中的元数据记录，绝不删除磁盘文件。
    """
    ids = request.form.getlist("book_ids")
    ids = [i for i in ids if i]
    if not ids:
        flash("未选择要删除的书籍", "warning")
        return redirect(request.referrer or url_for("index"))

    data = load_data()
    id_set = set(ids)
    removed = [b for b in data["books"] if b["book_id"] in id_set]
    data["books"] = [b for b in data["books"] if b["book_id"] not in id_set]
    for sh in data.get("shelves", []):
        sh["book_ids"] = [i for i in sh.get("book_ids", []) if i not in id_set]
    save_data(data)
    flash(f"已删除 {len(removed)} 本（仅删除记录，磁盘文件未动）", "success")
    # 回到发起页面，保持当前视图与筛选
    return redirect(request.referrer or url_for("index"))


@app.route("/books/bulk/tags", methods=["POST"])
def books_bulk_tags():
    """
    批量打标签：对选中的多本书追加或覆盖标签。
    - book_ids: 表单多值；tags: 逗号/顿号分隔；mode: append(默认) | replace
    """
    ids = [i for i in request.form.getlist("book_ids") if i]
    tags_raw = request.form.get("tags", "").strip()
    mode = request.form.get("mode", "append").strip()
    tags = [t.strip() for t in re.split(r"[,，、]", tags_raw) if t.strip()]
    if not ids or not tags:
        flash("请选择书籍并填写标签", "warning")
        return redirect(request.referrer or url_for("index"))
    data = load_data()
    id_set = set(ids)
    n = 0
    for b in data["books"]:
        if b["book_id"] not in id_set:
            continue
        if mode == "replace":
            b["tags"] = list(tags)
        else:
            merged = list(b.get("tags") or [])
            for t in tags:
                if t not in merged:
                    merged.append(t)
            b["tags"] = merged
        n += 1
    save_data(data)
    flash(f"已为 {n} 本书{'覆盖为' if mode == 'replace' else '追加'} "
          f"{len(tags)} 个标签", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/books/bulk/shelf", methods=["POST"])
def books_bulk_shelf():
    """
    批量加入书架：把选中的多本书加入一个或多个手动书架（智能书架自动跳过）。
    """
    ids = [i for i in request.form.getlist("book_ids") if i]
    shelf_ids = [i for i in request.form.getlist("shelf_ids") if i]
    if not ids or not shelf_ids:
        flash("请选择书籍与书架", "warning")
        return redirect(request.referrer or url_for("index"))
    data = load_data()
    id_set, shelf_set = set(ids), set(shelf_ids)
    added, skipped = 0, 0
    for s in _ensure_shelves(data):
        if s["id"] not in shelf_set or s.get("kind") == "smart":
            continue
        mem = s.setdefault("book_ids", [])
        for bid in ids:
            if bid in mem:
                skipped += 1
            else:
                mem.append(bid)
                added += 1
    save_data(data)
    flash(f"已将 {len(ids)} 本书加入 {len(shelf_ids)} 个书架"
          f"（新增 {added} 条成员，{skipped} 条已存在跳过）", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/nationality/run", methods=["POST"])
def nationality_run():
    """
    按【文件名规则】重新解析作者国籍（本地执行、不联网、秒级完成）：
    - 文件名含 [xx] 且可识别 → 对应国籍（如 [英]阿加莎·克里斯蒂 → 英国）
    - 无 [xx] 或无法识别 → 中国
    mode=fill_empty（默认）：只补空国籍；mode=overwrite：覆盖全部。
    """
    mode = request.form.get("mode", "fill_empty").strip()
    overwrite = mode == "overwrite"
    data = load_data()
    updated = skipped = 0
    for b in data["books"]:
        if not b.get("file_path"):
            skipped += 1
            continue
        nat = nationality_from_filename(b.get("file_path"))
        cur = (b.get("author_nationality") or "").strip()
        if overwrite or not cur:
            b["author_nationality"] = nat
            updated += 1
        else:
            skipped += 1
    save_data(data)
    flash(f"按文件名解析完成：更新 {updated} 本，跳过 {skipped} 本（无文件路径）",
          "success")
    return redirect(url_for("import_books"))


# ---------------------------------------------------------------------------
# 批量扫描导入
# ---------------------------------------------------------------------------

@app.route("/import", methods=["GET", "POST"])
def import_books():
    """
    批量导入（第一步·扫描预览）：
    接收本地文件夹路径，递归扫描 pdf/epub/mobi，列出候选文件供用户勾选。
    - 只扫描预览、不写库；真正入库由 /import/commit 按勾选执行
    - 书名按规则从文件名截取（引号前 / 「 - 」前）
    - 已存在同路径 / 同书名的文件自动标注为「已存在」（不可勾选）
    - 无效路径、无匹配文件给出友好提示
    """
    if request.method == "GET":
        d = load_data()
        return render_template("import_result.html", form_show=True,
                               results=None, nat=_nat_stats(d),
                               tag=_tag_stats(d))

    # 去掉用户可能粘贴的引号
    folder = request.form.get("folder", "").strip().strip('"').strip("'")
    if not folder or not os.path.isdir(folder):
        flash(f"无效的文件夹路径：{folder or '（未填写）'}，请检查后重试",
              "danger")
        d = load_data()
        return render_template("import_result.html", form_show=True,
                               results=None, nat=_nat_stats(d),
                               tag=_tag_stats(d))

    data = load_data()
    existing_paths = {b.get("file_path") for b in data["books"]}
    existing_titles = {b.get("title") for b in data["books"]}

    # 递归扫描
    found = []
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALLOWED_FORMATS:
                found.append(os.path.join(root, fn))
    found.sort()

    # 预览：逐个标注状态，不写库
    preview = []
    for full in found:
        title = title_from_filename(os.path.basename(full))
        fmt = os.path.splitext(full)[1].lstrip(".").lower()
        if full in existing_paths:
            preview.append({"full": full, "title": title, "format": fmt,
                            "state": "dup_path"})
        elif title in existing_titles:
            preview.append({"full": full, "title": title, "format": fmt,
                            "state": "dup_title"})
        else:
            preview.append({"full": full, "title": title, "format": fmt,
                            "state": "new"})

    new_count = sum(1 for p in preview if p["state"] == "new")
    dup_count = len(preview) - new_count
    # 可导入的排最上面，已存在的沉底（Python sort 稳定，同类内保持路径顺序）
    preview.sort(key=lambda p: (p["state"] != "new", p["full"]))
    flash(f"扫描到 {len(found)} 个文件：{new_count} 个可导入，"
          f"{dup_count} 个已存在（自动禁用），请勾选后点击「导入选中」",
          "info")
    results = {"folder": folder, "found": len(found), "preview": preview}
    return render_template("import_result.html", form_show=True,
                           results=results, nat=_nat_stats(data),
                           tag=_tag_stats(data))


@app.route("/import/commit", methods=["POST"])
def import_commit():
    """
    批量导入（第二步·提交勾选）：
    按用户勾选的文件路径列表真正写入书库。
    - 重新查重（预览到提交之间库可能已变化），只导入仍有效的文件
    - 仅登记元数据，不移动 / 不删除任何磁盘文件
    """
    folder = request.form.get("folder", "").strip().strip('"').strip("'")
    paths = [p.strip() for p in request.form.getlist("paths") if p and p.strip()]

    data = load_data()
    existing_paths = {b.get("file_path") for b in data["books"]}
    existing_titles = {b.get("title") for b in data["books"]}

    added, skipped_path, skipped_title, invalid = [], [], [], []
    for full in paths:
        ext_dotted = os.path.splitext(full)[1].lower()      # 带点，用于格式校验
        ext = ext_dotted.lstrip(".")                        # 不带点，用于入库存储
        if not os.path.isfile(full) or ext_dotted not in ALLOWED_FORMATS:
            invalid.append(full)
            continue
        if full in existing_paths:
            skipped_path.append(full)
            continue
        # 书名：按规则从文件名截取（如「丑闻 - [日]远藤周作.epub」→「丑闻」）
        title = title_from_filename(os.path.basename(full))
        if title in existing_titles:
            skipped_title.append((full, title))
            continue
        book = {
            "book_id": uuid.uuid4().hex,
            "title": title,
            "subtitle": "",
            "author": "",
            "author_nationality": nationality_from_filename(full),
            "series": "",
            "series_number": 0,
            "publisher": "",
            "publish_year": 0,
            "isbn": "",
            "file_path": full,
            "file_format": ext,
            "cover_path": "",
            "rating": 0,
            "tags": [],
            "status": "未读",
            "notes": "",
            "added_time": now_str(),
        }
        data["books"].append(book)
        existing_paths.add(full)
        existing_titles.add(title)
        added.append(book)

    save_data(data)
    flash(f"成功导入 {len(added)} 本，"
          f"跳过重复路径 {len(skipped_path)} 个，"
          f"跳过重复书名 {len(skipped_title)} 个，"
          f"无效文件 {len(invalid)} 个", "success")
    results = {"folder": folder, "found": len(paths),
               "added": added,
               "skipped_path": skipped_path,
               "skipped_title": skipped_title}
    return render_template("import_result.html", form_show=True,
                           results=results, nat=_nat_stats(data),
                           tag=_tag_stats(data))


# ---------------------------------------------------------------------------
# 批量路径修正（更换电脑 / 移动书库目录后修复失效路径）
# ---------------------------------------------------------------------------

@app.route("/paths/run", methods=["POST"])
def paths_repair():
    """
    批量路径修正（工具合集页表单）：输入「旧路径前缀 → 新路径前缀」，
    一键更新全部书籍的 file_path（可选 cover_path）。
    用于更换电脑、移动书库目录后快速修复失效路径。
    """
    old_prefix = request.form.get("old_prefix", "").strip()
    new_prefix = request.form.get("new_prefix", "").strip()
    fix_file = request.form.get("fix_file") == "on"
    fix_cover = request.form.get("fix_cover") == "on"

    # ---- 校验 ----
    if not old_prefix or not new_prefix:
        flash("旧/新路径前缀不能为空", "danger")
        return redirect(url_for("import_books"))
    if old_prefix.lower() == new_prefix.lower():
        flash("新旧路径前缀不能相同", "danger")
        return redirect(url_for("import_books"))
    if not fix_file and not fix_cover:
        flash("请至少勾选一种要修正的路径（书籍文件 / 封面）", "warning")
        return redirect(url_for("import_books"))

    data = load_data()
    old_l = old_prefix.lower()
    changed = []  # 记录每一条被修改的路径

    for b in data["books"]:
        if fix_file:
            p = b.get("file_path", "")
            if p and p.lower().startswith(old_l):
                b["file_path"] = new_prefix + p[len(old_prefix):]
                changed.append({"title": b.get("title", ""), "field": "书籍文件",
                                "old": p, "new": b["file_path"]})
        if fix_cover:
            c = b.get("cover_path", "")
            # 仅修正本地路径：空值、http(s) URL 自动跳过
            if (c and not c.lower().startswith(("http://", "https://"))
                    and c.lower().startswith(old_l)):
                b["cover_path"] = new_prefix + c[len(old_prefix):]
                changed.append({"title": b.get("title", ""), "field": "封面",
                                "old": c, "new": b["cover_path"]})

    if changed:
        save_data(data)
        flash(f"已修正 {len(changed)} 条路径", "success")
    else:
        flash("没有找到以该前缀开头的路径，请检查旧前缀是否正确", "warning")
    return redirect(url_for("import_books"))


# ---------------------------------------------------------------------------
# 丛书管理
# ---------------------------------------------------------------------------

@app.route("/series")
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


# ---------------------------------------------------------------------------
# 打开书籍 / 导出
# ---------------------------------------------------------------------------

@app.route("/open/<book_id>")
def open_book(book_id):
    """调用系统默认程序打开本地书籍文件；路径不存在时页面弹出警告。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    path = book.get("file_path", "")
    if not path or not os.path.exists(path):
        flash(f"文件不存在：{path or '（未填写文件路径）'}，"
              f"请先在编辑页补充或修正文件路径", "warning")
        return redirect(url_for("book_detail", book_id=book_id))
    try:
        open_file_with_default_app(path)
        flash(f"已调用系统默认程序打开：{os.path.basename(path)}", "success")
    except Exception as e:
        flash(f"打开文件失败：{e}", "danger")
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/download/<book_id>")
def download_book(book_id):
    """下载书籍文件到本地（以附件形式保存，不修改原文件）。"""
    book = get_book(book_id)
    if not book:
        flash("书籍不存在", "danger")
        return redirect(url_for("index"))
    path = book.get("file_path", "")
    if not path or not os.path.exists(path):
        flash(f"文件不存在：{path or '（未填写文件路径）'}，无法下载", "warning")
        return redirect(url_for("book_detail", book_id=book_id))
    try:
        return send_file(path, as_attachment=True,
                         download_name=os.path.basename(path))
    except Exception as e:
        flash(f"下载失败：{e}", "danger")
        return redirect(url_for("book_detail", book_id=book_id))


@app.route("/restore", methods=["POST"])
def restore_json():
    """上传 library.json 恢复书库：merge（合并去重）或 replace（覆盖，先备份）。"""
    mode = request.form.get("mode", "merge")
    f = request.files.get("file")
    if not f or not f.filename:
        flash("未选择 JSON 文件", "danger")
        return redirect(url_for("import_books"))
    try:
        incoming = json.loads(f.read().decode("utf-8"))
    except Exception as e:
        flash(f"JSON 解析失败：{e}", "danger")
        return redirect(url_for("import_books"))
    if not isinstance(incoming, dict) or "books" not in incoming:
        flash("不是有效的书库 JSON（缺少 books 字段）", "danger")
        return redirect(url_for("import_books"))

    data = load_data()
    if mode == "replace":
        backup_path = LIBRARY_FILE + ".bak_restore"
        try:
            shutil.copyfile(LIBRARY_FILE, backup_path)
        except Exception:
            pass
        data = {"version": incoming.get("version", 1),
                "books": incoming.get("books", []),
                "shelves": incoming.get("shelves", [])}
        flash("已用上传的 JSON 覆盖书库（原库已备份为 library.json.bak_restore）", "success")
    else:  # merge
        existing_ids = {b.get("book_id") for b in data["books"]}
        existing_paths = {b.get("file_path") for b in data["books"] if b.get("file_path")}
        added = 0
        for b in incoming.get("books", []):
            if not isinstance(b, dict):
                continue
            if b.get("book_id") in existing_ids:
                continue
            if b.get("file_path") and b.get("file_path") in existing_paths:
                continue
            data["books"].append(b)
            existing_ids.add(b.get("book_id"))
            added += 1
        inc_shelves = incoming.get("shelves", []) or []
        cur_shelf_ids = {s.get("id") for s in data.get("shelves", []) if isinstance(s, dict)}
        for s in inc_shelves:
            if isinstance(s, dict) and s.get("id") and s.get("id") not in cur_shelf_ids:
                data.setdefault("shelves", []).append(s)
                cur_shelf_ids.add(s.get("id"))
        flash(f"已合并导入 {added} 本新书籍" + (f"、{len(inc_shelves)} 个书架" if inc_shelves else ""), "success")
    save_data(data)
    return redirect(url_for("index"))


@app.route("/export")
def export_json():
    """将整个书库元数据导出为 JSON 下载。"""
    data = load_data()
    content = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"library_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        content,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# 在线发布（GitHub Pages 只读浏览站）：导出数据 -> git commit -> push
# ---------------------------------------------------------------------------


@app.context_processor
def inject_publish_state():
    """向所有模板注入上次发布状态（供侧边栏展示）。"""
    return {"publish_state": _read_publish_state()}


@app.route("/publish", methods=["POST"])
def publish_online():
    """
    一键发布到 GitHub Pages 只读浏览站：
    1) 调用 export_data.export_to 导出净化版数据 + 封面（打包版无需 python 子进程）
    2) 与站点现有数据对比，统计 新增/移除/变化 数量
    3) git add/commit/push（首次推送会弹 GitHub 登录窗口；需要本机装有 git）
    4) 记录发布状态（时间 + 数量）到 data/publish_state.json
    设置环境变量 PUBLISH_DRY_RUN=1 可跳过 git 步骤（测试用）。
    站点目录解析：环境变量 SITE_DIR > data/config.json 的 site_dir > 默认路径。
    """
    site = get_site_dir()
    if not os.path.isdir(site):
        return jsonify({"ok": False,
                        "message": f"在线站点目录不存在：{site}。"
                                   "若换到新电脑使用，请先克隆站点仓库，并把路径写入 "
                                   "data/config.json 的 site_dir 字段（或设置环境变量 SITE_DIR）。"})
    try:
        # 1) 读取上次发布到站点的数据（用于 diff）
        old_books = []
        old_json = os.path.join(site, "data", "library.json")
        if os.path.isfile(old_json):
            try:
                old_books = json.load(open(old_json, encoding="utf-8")) \
                    .get("books", [])
            except Exception:
                old_books = []
        # 2) 导出最新数据（模块内函数调用，打包版/源码版通用）
        try:
            export_data.export_to(site, LIBRARY_FILE, COVER_UPLOAD_DIR)
        except FileNotFoundError as e:
            return jsonify({"ok": False, "message": f"数据导出失败：{e}"})
        new_books = json.load(open(old_json, encoding="utf-8")).get("books", [])
        # 3) 统计更新数量
        added, removed, changed = _diff_books(old_books, new_books)
        # 4) git 提交并推送（测试模式可跳过）
        push_err = ""
        if os.environ.get("PUBLISH_DRY_RUN") != "1":
            def _git(*args):
                return subprocess.run(["git"] + list(args), cwd=site,
                                      capture_output=True, text=True,
                                      timeout=120)
            _git("add", "-A")
            _git("commit", "-m", f"update library data {now_str()}")
            g3 = _git("push")
            if g3.returncode != 0:
                push_err = (g3.stderr or g3.stdout or "").strip()[-200:]
        # 5) 记录状态
        state = {"last_time": now_str(),
                 "added": len(added), "removed": len(removed),
                 "changed": len(changed), "total": len(new_books)}
        _save_publish_state(state)
        msg = ("推送失败：" + push_err) if push_err else \
            "发布成功，在线站 1-2 分钟后自动更新"
        return jsonify({"ok": not push_err, "message": msg,
                        "added": len(added), "removed": len(removed),
                        "changed": len(changed), "total": len(new_books),
                        "last_time": state["last_time"]})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "发布超时（导出或推送耗时过长）"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"发布异常：{e}"})


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def _port_free(port):
    """检测本地端口是否空闲（空闲返回 True）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _run_packaged():
    """
    打包版启动入口：
    - 无控制台窗口（--noconsole），日志写 data/app.log 便于排错
    - 首次运行自动建空书库与封面目录
    - 端口 5000 起自动找空闲端口
    - 后台线程探测端口就绪后自动打开默认浏览器
    - 强制 debug=False / use_reloader=False（reloader 在打包环境会 fork 导致闪退）
    """
    import logging
    import threading
    import webbrowser
    import urllib.request

    # 数据目录与封面目录就绪（首次运行自动创建）
    try:
        ensure_data_dir()
        load_data()
        os.makedirs(COVER_UPLOAD_DIR, exist_ok=True)
    except Exception:
        pass

    # 日志落盘
    try:
        logging.basicConfig(
            filename=os.path.join(DATA_DIR, "app.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            encoding="utf-8")
        logging.info("=== 程序启动 v%s (PID=%s) 数据目录: %s",
                     APP_VERSION, os.getpid(), RUNTIME_DIR)
    except Exception:
        pass

    # 端口自动选择：5000 起找第一个空闲
    base = int(os.environ.get("PORT", "5000"))
    port = base
    for _ in range(10):
        if _port_free(port):
            break
        port += 1
    url = "http://127.0.0.1:%d" % port

    # 后台线程：端口就绪后自动打开浏览器
    def _open_browser_when_ready():
        for _ in range(60):            # 最多等约 30 秒
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(0.5)

    # 设置环境变量 NO_BROWSER=1 可跳过自动开浏览器（自动化测试或仅需后台服务时）
    if os.environ.get("NO_BROWSER", "") != "1":
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    try:
        logging.info("监听端口 %d → %s", port, url)
    except Exception:
        pass
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True,
            use_reloader=False)


if __name__ == "__main__":
    if IS_FROZEN:
        _run_packaged()
    else:
        # 本地源码运行：浏览器访问 http://127.0.0.1:5000
        # 调试模式默认开启（改代码自动重载），如需关闭设置环境变量 FLASK_DEBUG=0
        # 端口可用环境变量 PORT 覆盖（如 PORT=5001 python app.py）
        debug = os.environ.get("FLASK_DEBUG", "1") != "0"
        port = int(os.environ.get("PORT", "5000"))
        app.run(host="127.0.0.1", port=port, debug=debug, threaded=True)
