# -*- coding: utf-8 -*-
"""管理工具路由：统计仪表盘、批量扫描导入、作者国籍、路径修正、
书库恢复/导出，以及在线发布。"""

from datetime import datetime
import export_data
import json
import os
import shutil
import subprocess
import uuid
from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from shelfmark.books import _tag_stats
from shelfmark.nationality import _nat_stats, nationality_from_filename
from shelfmark.paths import (
    ALLOWED_FORMATS,
    COVER_UPLOAD_DIR,
    LIBRARY_FILE,
    RATING_OPTIONS,
    STATUS_OPTIONS,
)
from shelfmark.publishing import _diff_books, _save_publish_state
from shelfmark.storage import get_site_dir, load_data, save_data
from shelfmark.utils import now_str, safe_num, title_from_filename


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


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.add_url_rule('/stats', 'stats_view', stats_view)
    app.add_url_rule('/import', 'import_books', import_books, methods=['GET', 'POST'])
    app.add_url_rule('/import/commit', 'import_commit', import_commit, methods=['POST'])
    app.add_url_rule('/paths/run', 'paths_repair', paths_repair, methods=['POST'])
    app.add_url_rule('/nationality/run', 'nationality_run', nationality_run, methods=['POST'])
    app.add_url_rule('/restore', 'restore_json', restore_json, methods=['POST'])
    app.add_url_rule('/export', 'export_json', export_json)
    app.add_url_rule('/publish', 'publish_online', publish_online, methods=['POST'])
