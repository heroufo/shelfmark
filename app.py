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
from shelfmark.views import register_all

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

# 注册全部路由：视图已按领域拆分到 shelfmark/views/ 下的各模块，
# 端点名与原单文件实现逐一对齐（模板里的 url_for 无需改动）。
register_all(app)


# ---------------------------------------------------------------------------
# 静态文件服务（用于加载本机磁盘上的封面图片）
# ---------------------------------------------------------------------------


if IS_FROZEN:
    # 打包版封面外置在 exe 旁 covers/ 目录；本路由把 /static/covers/<名> 转发过去。
    # 规则比 Flask 默认 /static/<path> 更具体，会优先命中；缺图回退内置占位图。
    @app.route("/static/covers/<path:filename>")
    def covers_external(filename):
        safe = os.path.basename(filename.replace("\\", "/"))
        if safe and os.path.isfile(os.path.join(COVER_UPLOAD_DIR, safe)):
            return send_from_directory(COVER_UPLOAD_DIR, safe)
        return redirect(url_for("static", filename="images/default_cover.svg"))


# ---------------------------------------------------------------------------
# 书库主页：搜索 / 筛选 / 排序 / 视图切换
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 新增 / 编辑 / 详情 / 删除
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 统计仪表盘（纯读 library.json，无写入）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 智能书架 / 收藏书架
#   - 普通书架（kind=normal）：手动把书加入 book_ids
#   - 智能书架（kind=smart）：按 rule 规则实时筛选全部书籍
# ---------------------------------------------------------------------------


# 把后端函数/常量注册为 Jinja 模板全局（模板中可直接调用）
app.jinja_env.globals["shelf_rule_text"] = shelf_rule_text
app.jinja_env.globals["RATING_OPTIONS"] = RATING_OPTIONS


# ---------------------------------------------------------------------------
# 批量扫描导入
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 批量路径修正（更换电脑 / 移动书库目录后修复失效路径）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 丛书管理
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 打开书籍 / 导出
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 在线发布（GitHub Pages 只读浏览站）：导出数据 -> git commit -> push
# ---------------------------------------------------------------------------


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
