# -*- coding: utf-8 -*-
"""前后端交互接口：本地文件服务、原生对话框、元数据查询、封面上传。"""

import os
import uuid
from flask import abort, jsonify, request, send_file

from shelfmark.dialogs import pick_file_dialog, pick_folder_dialog
from shelfmark.metadata import fetch_book_meta
from shelfmark.paths import (
    ALLOWED_COVER_EXT,
    COVER_UPLOAD_DIR,
    MAX_COVER_SIZE,
)


def serve_file(filepath):
    """按本地绝对路径返回文件内容（本工具为本地单用户工具）。"""
    if os.path.isfile(filepath):
        return send_file(filepath)
    abort(404)


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


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.add_url_rule('/file/<path:filepath>', 'serve_file', serve_file)
    app.add_url_rule('/api/browse_file', 'api_browse_file', api_browse_file)
    app.add_url_rule('/api/browse_folder', 'api_browse_folder', api_browse_folder)
    app.add_url_rule('/api/book_meta', 'api_book_meta', api_book_meta)
    app.add_url_rule('/api/upload_cover', 'api_upload_cover', api_upload_cover, methods=['POST'])
