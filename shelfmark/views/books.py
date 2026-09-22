# -*- coding: utf-8 -*-
"""书籍操作路由：新增、编辑、删除、豆瓣补全、批量操作、打开与下载。"""

import os
import re
import uuid
from flask import (
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from shelfmark.books import (
    _ensure_shelves,
    build_book_from_form,
    form_values_from,
    validate_book_form,
)
from shelfmark.dialogs import open_file_with_default_app
from shelfmark.metadata import (
    _fetch_meta_by_title,
    fetch_book_meta,
    refresh_book_blurb,
)
from shelfmark.paths import FORMAT_OPTIONS, RATING_OPTIONS, STATUS_OPTIONS
from shelfmark.storage import get_book, load_data, save_data
from shelfmark.utils import now_str, safe_num


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


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.add_url_rule('/book/add', 'book_add', book_add, methods=['GET', 'POST'])
    app.add_url_rule('/book/edit/<book_id>', 'book_edit', book_edit, methods=['GET', 'POST'])
    app.add_url_rule('/book/<book_id>/douban_update', 'book_douban_update', book_douban_update, methods=['POST'])
    app.add_url_rule('/book/<book_id>/refresh_blurb', 'refresh_blurb', refresh_blurb)
    app.add_url_rule('/book/delete/<book_id>', 'book_delete', book_delete, methods=['POST'])
    app.add_url_rule('/book/bulk_delete', 'book_bulk_delete', book_bulk_delete, methods=['POST'])
    app.add_url_rule('/books/bulk/tags', 'books_bulk_tags', books_bulk_tags, methods=['POST'])
    app.add_url_rule('/books/bulk/shelf', 'books_bulk_shelf', books_bulk_shelf, methods=['POST'])
    app.add_url_rule('/open/<book_id>', 'open_book', open_book)
    app.add_url_rule('/download/<book_id>', 'download_book', download_book)
