# -*- coding: utf-8 -*-
"""模板上下文注入（context processor）：书库统计、侧栏书架、发布状态。"""

from shelfmark.books import _ensure_shelves
from shelfmark.paths import APP_NAME, APP_VERSION, STATUS_OPTIONS
from shelfmark.publishing import _read_publish_state
from shelfmark.storage import load_data, site_dir_info


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


def inject_publish_state():
    """向所有模板注入上次发布状态与在线站点目录信息（供侧边栏展示）。"""
    return {
        "publish_state": _read_publish_state(),
        "site_info": site_dir_info(),
    }


def register(app):
    """把本模块的视图注册到 Flask 应用。

    这里用显式注册（app.add_url_rule）而不是装饰器，是为了让视图函数
    原样保留在模块顶层、便于单独调用与测试；端点名与原实现完全一致，
    因此模板中的 url_for 无需任何改动。
    """
    app.context_processor(inject_library_stats)
    app.context_processor(inject_nav_shelves)
    app.context_processor(inject_publish_state)
