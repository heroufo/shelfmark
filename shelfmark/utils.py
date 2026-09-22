# -*- coding: utf-8 -*-
"""通用工具函数：数值/标签/格式归一化、文本清洗、时间戳。
纯函数，无 Flask、无副作用，可独立单元测试。"""

from datetime import datetime
import os
import re

from shelfmark.paths import FORMAT_OPTIONS


def now_str():
    """返回当前时间字符串，作为入库时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_num(value, default=0):
    """把字符串 / 数字安全转成数字，转换失败返回 default。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


def normalize_tags(tags_str):
    """把逗号 / 空格 / 顿号分隔的标签字符串转成去重后的列表。"""
    parts = re.split(r"[,，、;\s]+", tags_str)
    seen = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return seen


def guess_format(path):
    """根据文件路径后缀猜测格式，猜不到返回空字符串。"""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in FORMAT_OPTIONS:
        return ext
    return "其他" if ext else ""


def title_from_filename(filename):
    """
    从文件名推导书名（按优先级逐级截取）：
    1. 去掉扩展名
    2. 取第一个引号（半角 " 或全角 “）之前的内容
       （如：三体 “地球往事” _ 刘慈欣.epub → 「三体」）
    3. 取「 - 」之前的内容（书名 - 作者 命名）
       （如：丑闻 - [日]远藤周作 → 「丑闻」）
    4. 去掉首尾空白与多余的下划线/连字符
    5. 截取结果为空时回退为完整文件名
    """
    title = os.path.splitext(filename)[0]
    for q in ('"', '\u201c'):          # 半角 " 或全角 “
        if q in title:
            title = title.split(q, 1)[0]
            break
    for sep in (' - ', '\uff0d', ' \u2014 '):   # 半角 -、全角 －、em dash
        if sep in title:
            title = title.split(sep, 1)[0]
            break
    title = title.strip().strip("_ -")
    if not title:
        title = os.path.splitext(filename)[0].strip()
    return title


def _strip_html(raw):
    """去掉 HTML 标签并规整空白与常见实体。"""
    text = re.sub(r"<[^>]+>", "", raw)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"),
                 ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def _truncate_cn(text, limit=200):
    """
    把文本压到 limit 字以内：
    - 优先按中文句末标点（。！？；）切句，逐句累加到接近 limit
    - 单句超长则直接硬截断
    - 被截断时末尾补省略号
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    parts = re.split(r"(?<=[。！？；])", text)
    out = ""
    for p in parts:
        if len(out) + len(p) <= limit:
            out += p
        else:
            break
    if not out:                       # 单句超长，直接硬截断
        out = text[:limit]
    if out != text:
        out = out.rstrip("，、；：,;: ") + "…"
    return out


def status_class(status):
    """阅读状态 → Bootstrap 徽章样式类。"""
    return {"未读": "secondary", "在读": "primary",
            "已读": "success", "搁置": "warning"}.get(status, "secondary")


def file_exists(path):
    """判断书籍文件路径在磁盘上是否存在。"""
    return bool(path) and os.path.exists(path)
