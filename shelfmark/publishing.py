# -*- coding: utf-8 -*-
"""在线只读浏览站（GitHub Pages）发布支持：发布状态读写、
书籍指纹与新旧数据差异统计。
实际的 git 命令与路由入口在视图层，这里只做纯数据计算。"""

import json

from shelfmark.paths import PUBLISH_STATE_FILE
from shelfmark.storage import ensure_data_dir


def _read_publish_state():
    """读取上次发布状态（时间 / 更新数量），失败返回空 dict。"""
    try:
        with open(PUBLISH_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_publish_state(state):
    """记录发布状态到 data/publish_state.json。"""
    try:
        ensure_data_dir()
        with open(PUBLISH_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _book_sig(b):
    """生成书籍的比对指纹（用于判断内容是否变化）。"""
    keys = ["title", "subtitle", "author", "series", "series_number",
            "publisher", "publish_year", "rating", "tags", "status",
            "cover_path", "blurb"]
    return json.dumps({k: b.get(k) for k in keys},
                      ensure_ascii=False, sort_keys=True)


def _diff_books(old_books, new_books):
    """对比两次发布的书库，返回 (新增 ids, 移除 ids, 内容变化 ids)。"""
    old_by_id = {b.get("book_id"): b for b in old_books}
    new_by_id = {b.get("book_id"): b for b in new_books}
    old_ids, new_ids = set(old_by_id), set(new_by_id)
    added = new_ids - old_ids
    removed = old_ids - new_ids
    changed = {bid for bid in (new_ids & old_ids)
               if _book_sig(new_by_id[bid]) != _book_sig(old_by_id[bid])}
    return added, removed, changed
