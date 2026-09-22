# -*- coding: utf-8 -*-
"""书架路由：列表、详情、创建、编辑、删除、加入/移出书籍。"""

from datetime import datetime
import uuid
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from shelfmark.books import _ensure_shelves, shelf_members, shelf_rule_text
from shelfmark.paths import STATUS_OPTIONS
from shelfmark.storage import load_data, save_data
from shelfmark.utils import normalize_tags, safe_num


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


def shelf_delete(shelf_id):
    """删除书架（仅删书架与成员关系，不动书籍记录与磁盘文件）。"""
    data = load_data()
    shelves = _ensure_shelves(data)
    name = next((s.get("name") for s in shelves if s["id"] == shelf_id), "")
    data["shelves"] = [s for s in shelves if s["id"] != shelf_id]
    save_data(data)
    flash(f"已删除书架《{name}》", "success")
    return redirect(url_for("shelves_view"))


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


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.add_url_rule('/shelves', 'shelves_view', shelves_view)
    app.add_url_rule('/shelf/<shelf_id>', 'shelf_detail', shelf_detail)
    app.add_url_rule('/shelf/create', 'shelf_create', shelf_create, methods=['POST'])
    app.add_url_rule('/shelf/add', 'shelf_add_book', shelf_add_book, methods=['POST'])
    app.add_url_rule('/shelf/<shelf_id>/remove', 'shelf_remove_book', shelf_remove_book, methods=['POST'])
    app.add_url_rule('/shelf/<shelf_id>/delete', 'shelf_delete', shelf_delete, methods=['POST'])
    app.add_url_rule('/shelf/<shelf_id>/edit', 'shelf_edit', shelf_edit, methods=['GET', 'POST'])
