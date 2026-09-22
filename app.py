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
# 程序名称与版本（排错与发布用；版本格式 主.次.修订）
# ---------------------------------------------------------------------------
APP_NAME = "Shelfmark"
APP_VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# 运行模式与路径（打包版 / 源码版 双基地）
# ---------------------------------------------------------------------------
# PyInstaller 打包（--onefile）后：
#   - sys.frozen = True
#   - RUNTIME_DIR = exe 所在目录 —— 用户可写数据区。书库 data/、封面 covers/、
#     日志、发布配置都放这里（换电脑 = 拷贝 exe + data + covers 即迁移）
#   - RES_DIR = exe 内部解压区 (_MEIPASS) —— 只读内置资源（模板 / 静态基础文件）
# 源码运行（python app.py / 启动图书馆.bat）时两者相同，行为完全不变。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    RUNTIME_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RES_DIR = getattr(sys, "_MEIPASS", RUNTIME_DIR)
else:
    RUNTIME_DIR = RES_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = RES_DIR          # 内置资源根（打包版=exe 内部；源码版=项目目录）
DATA_DIR = os.path.join(RUNTIME_DIR, "data")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 在线只读浏览站（GitHub Pages）发布状态文件与默认站点目录。
# 站点目录解析见 get_site_dir()：环境变量 SITE_DIR > data/config.json 的 site_dir > 默认约定。
# 默认约定 = 与程序目录【同级】的 library-web 文件夹 —— 不写死任何个人路径；
# 若站点仓库不在该位置，在 data/config.json 写入 {"site_dir": "你的路径"} 即可，无需改代码。
DEFAULT_SITE_DIR = os.path.join(
    os.path.dirname(os.path.normpath(RUNTIME_DIR)), "library-web")
PUBLISH_STATE_FILE = os.path.join(DATA_DIR, "publish_state.json")

# 批量导入支持的电子书格式（按扩展名筛选）
ALLOWED_FORMATS = {".pdf", ".epub", ".mobi"}

# 表单下拉选项
STATUS_OPTIONS = ["未读", "在读", "已读", "搁置"]
RATING_OPTIONS = [0, 1, 2, 3, 4, 5]
FORMAT_OPTIONS = ["pdf", "epub", "mobi", "其他"]

# 封面图片上传：封面图目录（运行时新增都写这里，打包版=exe 旁 covers/，源码版=static/covers/）
if IS_FROZEN:
    COVER_UPLOAD_DIR = os.path.join(RUNTIME_DIR, "covers")
else:
    COVER_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "covers")
ALLOWED_COVER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                     ".svg", ".bmp"}                             # 允许的图片格式
MAX_COVER_SIZE = 5 * 1024 * 1024                                 # 单张封面最大 5MB

# 分页 / 封面墙
PAGE_SIZE_LIST = 108     # 表格视图每页本数
PAGE_SIZE_CARDS = 108    # 封面墙每页本数
SHELF_COUNT = 9          # 「最近添加 / 随机发现」各展示本数

# 可排序字段 → 排序取值函数（key 函数）
SORTABLE_FIELDS = {
    "title": lambda b: (b.get("title") or "").lower(),
    "author": lambda b: (b.get("author") or "").lower(),
    "series": lambda b: ((b.get("series") or "").lower(),
                         safe_num(b.get("series_number"), 10 ** 9)),
    "publisher": lambda b: (b.get("publisher") or "").lower(),
    "publish_year": lambda b: safe_num(b.get("publish_year")),
    "rating": lambda b: safe_num(b.get("rating")),
    "pages": lambda b: safe_num(b.get("pages")),
    "status": lambda b: b.get("status") or "",
    "file_format": lambda b: (b.get("file_format") or "").lower(),
    "added_time": lambda b: b.get("added_time") or "",
}

# 旧版 sort 参数（兼容映射为 字段:方向）
LEGACY_SORT = {
    "added_desc": "added_time:desc",
    "added_asc": "added_time:asc",
    "series_number": "series:asc",
    "rating_desc": "rating:desc",
}


def recommend_related(book, books, limit=9):
    """
    相关书籍推荐（基于内容 Content-Based 的加权相似度算法，纯 Python 实现）：
    参考业界主流做法——用书籍元数据特征构建相似度，而非依赖用户行为
    （协同过滤需要大量用户评分数据，本地单用户场景不适用）。

    特征权重：
    - 标签 Jaccard 相似度  |交集|/|并集|  权重 3.0（最核心特征）
    - 丛书相同（同丛书分卷强相关）        权重 3.0
    - 作者相同                           权重 2.0
    - 出版社相同                         权重 1.0
    - 出版年相差 ≤ 2 年                   权重 0.5
    - 评分相同（弱信号）                  权重 0.3

    完全无关（总分 = 0）的书不参与推荐；返回前 limit 本。
    """
    def score(other):
        s = 0.0
        tags_a = set(book.get("tags") or [])
        tags_b = set(other.get("tags") or [])
        if tags_a and tags_b:
            s += 3.0 * len(tags_a & tags_b) / len(tags_a | tags_b)
        if book.get("series") and book.get("series") == other.get("series"):
            s += 3.0
        if book.get("author") and book.get("author") == other.get("author"):
            s += 2.0
        if (book.get("publisher")
                and book.get("publisher") == other.get("publisher")):
            s += 1.0
        ya = safe_num(book.get("publish_year"))
        yb = safe_num(other.get("publish_year"))
        if ya and yb and abs(ya - yb) <= 2:
            s += 0.5
        if book.get("rating") and book.get("rating") == other.get("rating"):
            s += 0.3
        return s

    scored = [(score(b), b) for b in books
              if b["book_id"] != book["book_id"]]
    scored = [(s, b) for s, b in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in scored[:limit]]


# ---------------------------------------------------------------------------
# 网络简介获取（详情页「简介」自动补全，数据源：豆瓣）
# ---------------------------------------------------------------------------

_DOUBAN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _http_get_text(url, timeout=12):
    """发起 GET 请求并返回解码后的文本；失败抛异常由调用方捕获。
    带 2 次自动重试（抗豆瓣偶发超时 / 短暂限流）。"""
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": _DOUBAN_UA,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://book.douban.com/",
            })
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ctx) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    raise last_err


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


# 豆瓣作者行国籍缩写 -> 全称（多字优先匹配）
_NATIONALITY_MAP = {
    # 双字及以上（精确）
    "印度尼西亚": "印度尼西亚", "沙特阿拉伯": "沙特阿拉伯", "白俄罗斯": "白俄罗斯",
    "哈萨克斯坦": "哈萨克斯坦", "孟加拉国": "孟加拉国", "斯里兰卡": "斯里兰卡",
    "新加坡": "新加坡", "马来西亚": "马来西亚", "菲律宾": "菲律宾",
    "巴基斯坦": "巴基斯坦", "阿富汗": "阿富汗", "委内瑞拉": "委内瑞拉",
    "哥伦比亚": "哥伦比亚", "阿根廷": "阿根廷", "澳大利亚": "澳大利亚",
    "新西兰": "新西兰", "加拿大": "加拿大", "爱尔兰": "爱尔兰",
    "冰岛": "冰岛", "瑞典": "瑞典", "挪威": "挪威", "丹麦": "丹麦",
    "芬兰": "芬兰", "瑞士": "瑞士", "奥地利": "奥地利", "波兰": "波兰",
    "捷克": "捷克", "匈牙利": "匈牙利", "罗马尼亚": "罗马尼亚",
    "保加利亚": "保加利亚", "乌克兰": "乌克兰", "希腊": "希腊",
    "土耳其": "土耳其", "以色列": "以色列", "印度": "印度",
    "伊朗": "伊朗", "伊拉克": "伊拉克", "叙利亚": "叙利亚",
    "越南": "越南", "泰国": "泰国", "缅甸": "缅甸",
    "巴西": "巴西", "智利": "智利", "秘鲁": "秘鲁",
    "墨西哥": "墨西哥", "古巴": "古巴", "南非": "南非", "埃及": "埃及",
    "肯尼亚": "肯尼亚", "尼日利亚": "尼日利亚",
    "葡萄牙": "葡萄牙", "比利时": "比利时", "塞尔维亚": "塞尔维亚",
    "克罗地亚": "克罗地亚", "斯洛文尼亚": "斯洛文尼亚",
    "爱沙尼亚": "爱沙尼亚", "拉脱维亚": "拉脱维亚", "立陶宛": "立陶宛",
    "埃塞俄比亚": "埃塞俄比亚", "摩洛哥": "摩洛哥", "尼泊尔": "尼泊尔",
    "蒙古": "蒙古", "乌拉圭": "乌拉圭", "厄瓜多尔": "厄瓜多尔",
    "玻利维亚": "玻利维亚", "牙买加": "牙买加", "加纳": "加纳",
    "塞内加尔": "塞内加尔", "突尼斯": "突尼斯", "阿尔及利亚": "阿尔及利亚",
    "苏丹": "苏丹", "乌干达": "乌干达", "坦桑尼亚": "坦桑尼亚",
    "津巴布韦": "津巴布韦", "赞比亚": "赞比亚", "安哥拉": "安哥拉",
    "莫桑比克": "莫桑比克", "喀麦隆": "喀麦隆", "刚果": "刚果",
    "哥伦比亚": "哥伦比亚", "爱沙尼亚": "爱沙尼亚",
    # 单字（常用）
    "中": "中国", "美": "美国", "英": "英国", "法": "法国", "德": "德国",
    "日": "日本", "韩": "韩国", "俄": "俄罗斯", "意": "意大利", "西": "西班牙",
    "荷": "荷兰", "挪": "挪威", "丹": "丹麦", "芬": "芬兰", "瑞": "瑞典",
    "波": "波兰", "捷": "捷克", "匈": "匈牙利", "奥": "奥地利", "比": "比利时",
    "葡": "葡萄牙", "希": "希腊", "墨": "墨西哥", "古": "古巴", "加": "加拿大",
    "澳": "澳大利亚", "新": "新西兰", "以": "以色列", "印": "印度", "巴": "巴西",
    "泰": "泰国", "越": "越南", "缅": "缅甸", "菲": "菲律宾", "马": "马来西亚",
}


def _parse_nationality(author_line):
    """从豆瓣作者行提取国籍，如「[挪] 格德·布兰腾伯格」→ 挪威；无标记返回 ''。"""
    try:
        m = re.search(r"\[([^\]]+)\]", author_line or "")
        if not m:
            return ""
        tag = m.group(1).strip()
        for k in sorted(_NATIONALITY_MAP, key=len, reverse=True):
            if tag == k or tag.startswith(k):
                return _NATIONALITY_MAP[k]
    except Exception:
        pass
    return ""


def nationality_from_filename(file_path):
    """
    从书籍文件名解析作者国籍（本地规则，不联网）：
    - 文件名含 [xx] 且 xx 能匹配国籍缩写 → 对应国籍
      （如「[英]阿加莎·克里斯蒂 - 东方快车谋杀案.pdf」→ 英国）
    - 无 [xx] 或标记无法识别 → 中国
    """
    try:
        fname = os.path.basename((file_path or "").replace("\\", "/"))
        m = re.search(r"\[([^\]]+)\]", fname)
        if not m:
            return "中国"
        tag = m.group(1).strip()
        for k in sorted(_NATIONALITY_MAP, key=len, reverse=True):
            if tag == k or tag.startswith(k):
                return _NATIONALITY_MAP[k]
    except Exception:
        pass
    return "中国"


def fetch_book_blurb(title, author=None, isbn=None):
    """
    根据书名（优先 ISBN）从豆瓣获取书籍内容简介，返回 ≤200 字的中文短介绍。
    网络不可用 / 被拦截 / 无结果时返回 None（调用方回退到原有 notes）。
    在线抓取可通过 data/config.json 的 online_metadata=false 整体关闭。
    """
    if not online_metadata_enabled():
        return None
    try:
        # 1) 搜索得到 subject id（豆瓣 suggest 对「书名 作者」组合、以及部分
        #    ISBN 查询支持不好；统一优先用「书名」单条件搜索，书名无果时再
        #    用「ISBN」兜底，命中后按书名二次筛选）
        def _suggest(q):
            try:
                return json.loads(_http_get_text(
                    "https://book.douban.com/j/subject_suggest?q="
                    + urllib.parse.quote(q), timeout=8)) or []
            except Exception:
                return []

        sug = []
        if title and title.strip():
            sug = _suggest(title.strip())
        if not sug and isbn:                      # 书名查不到 → 用 ISBN 兜底
            sug = _suggest(isbn.replace("-", "").replace(" ", ""))
        if not sug:
            return None
        # 优先选择与书名最匹配的一条
        target = (title or "").lower()
        cand = None
        if target:
            for it in sug:
                if target in (it.get("title") or "").lower():
                    cand = it
                    break
        if cand is None:
            cand = sug[0]
        sid = cand.get("id")
        if not sid:
            return None
        # 2) 抓取书籍页，提取第一个 .intro（即「内容简介」）
        html = _http_get_text(
            f"https://book.douban.com/subject/{sid}/", timeout=8)
        intros = re.findall(r'class="intro"[^>]*>(.*?)</div>', html, re.S)
        if not intros:
            return None
        text = _strip_html(intros[0])
        if not text:
            return None
        return _truncate_cn(text, 200)
    except Exception:
        return None


def _parse_subject_info(html):
    """从豆瓣书籍页 HTML 解析 info 区字段（作者/国籍/出版社/出版年/页数）。"""
    meta = {"author": "", "author_nationality": "", "publisher": "",
            "publish_year": "", "pages": ""}
    m = re.search(r'<div id="info"[^>]*>(.*?)</div>', html, re.S)
    if not m:
        return None
    for ln in re.split(r"<br\s*/?>", m.group(1)):
        km = re.search(r'class="pl"[^>]*>(.*?)</span>', ln, re.S)
        if not km:
            continue
        key = _strip_html(km.group(1)).strip(" ：: \t")
        # 值取 label 之后的部分，去掉前缀与常见尾缀（著/译/编）
        val = _strip_html(ln[km.end():]).strip(" ：: \t")
        # 删除人名前的国家/地区标记与空格（如「[挪] 格德·布兰腾伯格」→「格德·布兰腾伯格」）
        val = re.sub(r"^\[[^\]]*\]\s*", "", val)
        val = re.sub(r"\s*(著|译|编|编著|主编|原著)$", "", val)
        if key == "作者" and not meta["author"]:
            meta["author"] = val
            meta["author_nationality"] = _parse_nationality(_strip_html(ln))
        elif key == "出版社" and not meta["publisher"]:
            meta["publisher"] = val
        elif key == "出版年" and not meta["publish_year"]:
            ym = re.search(r"(19|20)\d{2}", val)
            if ym:
                meta["publish_year"] = ym.group(0)
        elif key == "页数" and not meta["pages"]:
            pm = re.search(r"\d+", val)
            if pm:
                meta["pages"] = pm.group(0)
    return meta


def fetch_book_meta(isbn):
    """
    根据 ISBN 从豆瓣获取书名 / 作者 / 作者国籍 / 出版社 / 出版年。
    返回 dict(title/author/nationality/publisher/publish_year)；任一步失败返回 None。

    注意：豆瓣 suggest 接口对纯 ISBN 查询基本返回空数组，因此
    suggest 失败后会用站内搜索页（subject_search）兜底拿 subject id。
    在线抓取可通过 data/config.json 的 online_metadata=false 整体关闭。
    """
    if not online_metadata_enabled():
        return None
    try:
        isbn_clean = (isbn or "").replace("-", "").replace(" ", "").strip()
        if not isbn_clean:
            return None

        # 1) 定位 subject id：suggest 优先，失败用站内搜索页兜底
        sid = ""
        title_hint = ""
        try:
            sug = json.loads(_http_get_text(
                "https://book.douban.com/j/subject_suggest?q="
                + urllib.parse.quote(isbn_clean), timeout=8)) or []
            for it in sug:                     # ISBN 完全匹配优先
                it_isbn = (it.get("isbn") or "").replace("-", "").replace(" ", "")
                if it_isbn and it_isbn == isbn_clean:
                    sid = it.get("id") or ""
                    title_hint = (it.get("title") or "").strip()
                    break
            if not sid and sug:
                sid = sug[0].get("id") or ""
                title_hint = (sug[0].get("title") or "").strip()
        except Exception:
            pass
        if not sid:
            try:
                html = _http_get_text(
                    "https://search.douban.com/book/subject_search?search_text="
                    + urllib.parse.quote(isbn_clean), timeout=8)
                ids = re.findall(r'/subject/(\d+)/', html)
                for i in ids:
                    if i.isdigit():
                        sid = i
                        break
            except Exception:
                pass
        if not sid:
            return None

        # 2) 抓取书籍页：书名（suggest 没有时从页面取）+ info 区字段
        html = _http_get_text(
            f"https://book.douban.com/subject/{sid}/", timeout=8)
        if not title_hint:
            tm = re.search(r'property="v:itemreviewed"[^>]*>([^<]+)<', html)
            if tm:
                title_hint = tm.group(1).strip()
        info = _parse_subject_info(html)
        if info is None:
            return None
        return {"title": title_hint, **info}
    except Exception:
        return None


def _fetch_meta_by_title(title):
    """无 ISBN 时按书名从豆瓣获取元数据（suggest 拿 subject id → 书籍页解析）。

    在线抓取可通过 data/config.json 的 online_metadata=false 整体关闭。
    """
    if not online_metadata_enabled():
        return None
    try:
        q = (title or "").strip()
        if not q:
            return None
        sug = json.loads(_http_get_text(
            "https://book.douban.com/j/subject_suggest?q="
            + urllib.parse.quote(q), timeout=8)) or []
        if not sug:
            return None
        sid = sug[0].get("id")
        if not sid:
            return None
        html = _http_get_text(
            f"https://book.douban.com/subject/{sid}/", timeout=8)
        info = _parse_subject_info(html)
        return info
    except Exception:
        return None


def refresh_book_blurb(book_id):
    """重新从网络拉取简介并写回库；返回获取到的简介（失败为 None）。"""
    book = get_book(book_id)
    if not book:
        return None
    blurb = fetch_book_blurb(book.get("title"),
                             book.get("author"), book.get("isbn"))
    if not blurb:
        return None
    data = load_data()
    for i, b in enumerate(data["books"]):
        if b["book_id"] == book_id:
            data["books"][i]["blurb"] = blurb
            break
    save_data(data)
    return blurb


app = Flask(__name__)
# 本地单用户工具，密钥仅用于 flash 消息签名
app.secret_key = "ebook-manager-local-secret-key"


# ---------------------------------------------------------------------------
# 数据持久化
# ---------------------------------------------------------------------------

def now_str():
    """返回当前时间字符串，作为入库时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_data_dir():
    """确保 data/ 目录存在。"""
    os.makedirs(DATA_DIR, exist_ok=True)


def load_config():
    """读取 data/config.json（不存在 / 损坏返回空字典，不抛异常）。"""
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
    except Exception:
        pass
    return {}


def save_config(cfg):
    """写 data/config.json（原子写；失败静默，不影响主流程）。"""
    try:
        ensure_data_dir()
        tmp_path = CONFIG_FILE + "." + uuid.uuid4().hex + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp_path, CONFIG_FILE)
    except Exception:
        pass


def get_site_dir():
    """
    在线站点目录解析优先级：
      环境变量 SITE_DIR > data/config.json 的 site_dir 字段 > 内置默认路径。
    支持换电脑后把站点仓库路径写入 data/config.json 即可发布，无需改代码。
    """
    env = os.environ.get("SITE_DIR")
    if env:
        return env.strip().strip('"').strip("'")
    site = (load_config().get("site_dir") or DEFAULT_SITE_DIR)
    return site.strip().strip('"').strip("'")


def online_metadata_enabled():
    """
    是否允许访问在线元数据源（豆瓣读书）。

    - 默认开启（保持开箱即用）。
    - 如需完全离线运行，在 data/config.json 写入 {"online_metadata": false}；
      关闭后所有在线抓取（元数据补全 / 简介）直接跳过，程序其余功能不受影响。
    """
    try:
        return bool(load_config().get("online_metadata", True))
    except Exception:
        return True


def load_data():
    """
    加载书库数据。
    - 文件不存在时创建默认空库并返回
    - 文件损坏 / 格式错误时备份原文件并重建空库（保证程序不崩溃）
    """
    ensure_data_dir()
    if not os.path.exists(LIBRARY_FILE):
        empty = {"version": 1, "books": []}
        save_data(empty)
        return empty
    try:
        with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "books" not in data:
            raise ValueError("数据格式不正确")
        return data
    except Exception:
        # 原文件损坏：备份为 .bak 后重建空库
        try:
            os.replace(LIBRARY_FILE, LIBRARY_FILE + ".bak")
        except Exception:
            pass
        empty = {"version": 1, "books": []}
        save_data(empty)
        return empty


def save_data(data):
    """原子写回：先写临时文件再替换，避免中途写入导致 JSON 损坏。
    Windows 上目标文件可能被杀毒 / 其他进程短暂锁定，故对 replace 加重试与兜底。
    """
    ensure_data_dir()
    # 唯一临时文件名，避免多进程 / 多线程共用同一 .tmp 互相覆盖
    tmp_path = "%s.%s.tmp" % (LIBRARY_FILE, uuid.uuid4().hex)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp_path, LIBRARY_FILE)
    except Exception:
        # 清理自己产生的临时文件，避免残留堆积
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def _atomic_replace(tmp_path, target):
    """跨平台原子替换。Windows 下目标可能被锁，或运行环境（如沙箱）拦截
    删除/替换操作，因此按序兜底：
      1) os.replace 原子替换（重试 5 次，抗瞬时锁）
      2) 复制覆盖 shutil.copy2（只写不删，兼容沙箱拦截删除的场景）
      3) 备份后删除目标再 rename（对目标被独占锁更彻底）
      4) 保留 .recover 便于手动恢复，并抛出原错误
    """
    last_err = None
    for attempt in range(5):
        try:
            os.replace(tmp_path, target)
            return
        except (PermissionError, OSError) as e:
            last_err = e
            # 瞬时锁（杀毒扫描 / 其他进程短暂读）通常很快释放，短暂停顿后重试
            time.sleep(0.3 * (attempt + 1))
    # 兜底 A：直接复制覆盖（不删除目标文件，兼容沙箱拦截删除/替换的场景）
    try:
        if os.path.exists(target):
            shutil.copy2(target, target + ".bak")
        shutil.copy2(tmp_path, target)
        return
    except Exception as e:
        last_err = e
    # 兜底 B：先备份，再强制移除目标后 rename
    try:
        if os.path.exists(target):
            shutil.copy2(target, target + ".bak")
        if os.path.exists(target):
            os.remove(target)
        os.rename(tmp_path, target)
        return
    except Exception:
        pass
    # 彻底失败：把临时文件保留为 .recover 以便手动恢复，并抛出原错误
    try:
        if os.path.exists(tmp_path):
            shutil.copy2(tmp_path, target + ".recover")
    except Exception:
        pass
    raise last_err


def get_book(book_id):
    """按 book_id 查找书籍记录，找不到返回 None。"""
    data = load_data()
    for book in data["books"]:
        if book["book_id"] == book_id:
            return book
    return None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

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


def open_file_with_default_app(path):
    """跨平台调用系统默认程序打开文件（Windows: startfile）。"""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


_DIALOG_PYTHON_CACHE = None  # 缓存带 tkinter 的 pythonw 路径（仅命中时缓存，避免每次点击重新探测）

def _find_dialog_python():
    """
    找到带 tkinter 的 pythonw / python 解释器（用于弹出系统原生文件对话框）。
    结果会缓存，避免每次点击「浏览…」都重新探测所有 Python 候选（这是卡顿主因）。
    """
    global _DIALOG_PYTHON_CACHE
    if _DIALOG_PYTHON_CACHE is not None:
        return _DIALOG_PYTHON_CACHE
    candidates = [
        # 当前解释器（venv 场景最常见）
        os.path.join(os.path.dirname(sys.executable or ""), "pythonw.exe"),
        sys.executable,
        # 微软商店版 / 官方安装版的常见位置（用环境变量，不写死用户名）
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python313\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python312\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python311\pythonw.exe"),
        r"C:\Python313\pythonw.exe",
        r"C:\Python312\pythonw.exe",
        r"C:\Python311\pythonw.exe",
        # PATH 中的兜底（探测到不带 tkinter 会自动跳过）
        shutil.which("pythonw"),
        shutil.which("python"),
    ]
    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "import tkinter"],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                _DIALOG_PYTHON_CACHE = cand
                return cand
        except Exception:
            continue
    return None


def pick_file_dialog():
    """
    弹出系统原生「选择文件」对话框，返回用户选中的本地文件路径。
    - 打包版：ctypes 调 Windows 原生 API（GetOpenFileNameW），零 Python 依赖
    - 源码版：以子进程方式调用带 tkinter 的系统 pythonw.exe
      执行 file_dialog_helper.py（与历史行为一致）
    - 用户取消或任何一步失败均返回 None，不抛异常
    """
    return _pick_dialog("file")


def pick_folder_dialog():
    """
    弹出系统原生「选择目录」对话框（批量导入用），返回选中的文件夹路径。
    与 pick_file_dialog 同一机制，仅对话框类型不同。
    """
    return _pick_dialog("folder")


def _pick_dialog(mode="file"):
    """
    pick_file_dialog / pick_folder_dialog 的公共实现：
    - 打包版：直接走 _native_dialog（Windows 原生 API）
    - 源码版：子进程调用 file_dialog_helper.py（mode: file|folder）并读取输出文件
    """
    if IS_FROZEN:
        try:
            return _native_dialog(mode)
        except Exception:
            return None
    helper = os.path.join(BASE_DIR, "file_dialog_helper.py")
    pythonw = _find_dialog_python()
    if not os.path.isfile(helper) or not pythonw:
        return None
    tmp_file = os.path.join(tempfile.gettempdir(),
                            "ebook_pick_" + uuid.uuid4().hex + ".txt")
    try:
        subprocess.run([pythonw, helper, tmp_file, mode], timeout=300)
        if os.path.exists(tmp_file):
            with open(tmp_file, "r", encoding="utf-8") as f:
                path = f.read().strip()
            return path or None
    except Exception:
        return None
    finally:
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception:
            pass
    return None


def _native_log(msg):
    """
    把原生对话框相关诊断信息追加写入 data/app.log。
    打包版无控制台窗口，出错只能靠日志排查，故任何异常都留痕。
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "app.log"), "a",
                  encoding="utf-8") as f:
            f.write("[%s] %s\n"
                    % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _native_dialog(mode="file"):
    """
    打包版专用：Windows 原生文件/目录选择对话框（纯 ctypes，无 tkinter）。
    可在任意线程调用（模态对话框自带消息循环）。
    mode: file → GetOpenFileNameW 选择电子书文件；folder → SHBrowseForFolderW 选择目录。
    取消或失败返回 None（失败原因写 data/app.log）。
    """
    import ctypes
    from ctypes import wintypes

    try:
        if mode == "folder":
            return _native_pick_folder(ctypes, wintypes)
        return _native_pick_file(ctypes, wintypes)
    except Exception as e:
        _native_log("原生对话框异常(mode=%s): %r" % (mode, e))
        return None


def _native_pick_folder(ctypes, wintypes):
    """SHBrowseForFolderW 目录选择框。返回目录路径或 None。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    # 必须显式声明 restype：SHBrowseForFolderW 返回 PIDL 指针，
    # 默认 c_long 会把 64 位地址截断，导致后续转换访问违例。
    browse = shell32.SHBrowseForFolderW
    browse.argtypes = [ctypes.c_void_p]
    browse.restype = ctypes.c_void_p
    get_path = shell32.SHGetPathFromIDListW
    get_path.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    get_path.restype = wintypes.BOOL

    ole32.CoInitialize(None)
    try:
        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                # 用 c_void_p 承载缓冲区地址：若声明 LPWSTR，读取字段会返回
                # Python str（无 .value），且无法保证缓冲区生命周期。
                ("pszDisplayName", ctypes.c_void_p),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            ]

        display_buf = ctypes.create_unicode_buffer(260)
        path_buf = ctypes.create_unicode_buffer(4096)
        bi = BROWSEINFOW()
        bi.hwndOwner = None
        bi.pszDisplayName = ctypes.addressof(display_buf)
        bi.lpszTitle = "选择电子书目录（批量导入）"
        # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE（新版树形对话框，可输入路径）
        bi.ulFlags = 0x00000001 | 0x00000040
        pidl = browse(ctypes.addressof(bi))
        if pidl:
            if get_path(pidl, ctypes.addressof(path_buf)) and path_buf.value:
                return path_buf.value
            _native_log("目录选择：PIDL 转路径失败 pidl=%s" % pidl)
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass
    return None


def _native_pick_file(ctypes, wintypes):
    """GetOpenFileNameW 文件选择框（电子书格式过滤）。返回文件路径或 None。"""
    comdlg32 = ctypes.windll.comdlg32
    ole32 = ctypes.windll.ole32

    get_open = comdlg32.GetOpenFileNameW
    get_open.argtypes = [ctypes.c_void_p]
    get_open.restype = wintypes.BOOL
    ext_err = comdlg32.CommDlgExtendedError
    ext_err.argtypes = []
    ext_err.restype = wintypes.DWORD

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", ctypes.c_void_p),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            # lpstrFile 必须是可写缓冲区；用 c_void_p + addressof 赋值，
            # 结果直接从 path_buf 读取。若声明为 LPWSTR，读取字段得到的是
            # Python str（再取 .value 会 AttributeError）。
            ("lpstrFile", ctypes.c_void_p),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", ctypes.c_void_p),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
        ]

    ole32.CoInitialize(None)
    try:
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = None
        ofn.lpstrFilter = ("电子书文件\0*.pdf;*.epub;*.mobi\0"
                           "所有文件\0*.*\0\0")
        ofn.nFilterIndex = 1
        ofn.lpstrTitle = "选择电子书文件"
        path_buf = ctypes.create_unicode_buffer(32768)
        ofn.lpstrFile = ctypes.addressof(path_buf)
        ofn.nMaxFile = 32768
        ofn.lpstrInitialDir = None
        # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY
        # | OFN_EXPLORER | OFN_ENABLESIZING
        ofn.flags = (0x00001000 | 0x00000800 | 0x00000004
                     | 0x00080000 | 0x00800000)
        if get_open(ctypes.addressof(ofn)):
            return path_buf.value or None
        # 返回 0：用户取消（错误码 0）或结构体/参数错误（非 0 错误码）
        _native_log("文件选择未返回路径 CommDlgExtendedError=%d" % ext_err())
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass
    return None


def validate_book_form(form):
    """
    表单校验：
    - 书名必填
    - 卷号若填写必须是数字
    - 出版年若填写必须是 4 位数字
    返回错误信息字符串，通过校验返回 None。
    """
    if not form.get("title", "").strip():
        return "书名不能为空"
    sn = form.get("series_number", "").strip()
    if sn and not sn.isdigit():
        return "卷号必须是数字（例如：1、2、3）"
    py = form.get("publish_year", "").strip()
    if py and (not py.isdigit() or len(py) != 4):
        return "出版年必须是 4 位数字（例如：2020）"
    return None


def build_book_from_form(form):
    """把表单数据整理成一条书籍记录（不含 book_id / added_time）。"""
    sn_str = form.get("series_number", "").strip()
    py_str = form.get("publish_year", "").strip()
    return {
        "title": form.get("title", "").strip(),
        "subtitle": form.get("subtitle", "").strip(),
        "author": form.get("author", "").strip(),
        "author_nationality": (form.get("author_nationality", "").strip()
                               or nationality_from_filename(
                                   form.get("file_path", ""))),
        "series": form.get("series", "").strip(),
        "series_number": safe_num(sn_str) if sn_str else 0,
        "publisher": form.get("publisher", "").strip(),
        "publish_year": safe_num(py_str) if py_str else 0,
        "pages": safe_num(form.get("pages", "0"), 0),
        "isbn": form.get("isbn", "").strip(),
        "file_path": form.get("file_path", "").strip(),
        "file_format": form.get("file_format", "").strip()
                      or guess_format(form.get("file_path", "")),
        "cover_path": form.get("cover_path", "").strip(),
        "rating": safe_num(form.get("rating", "0"), 0),
        "tags": normalize_tags(form.get("tags", "")),
        "status": form.get("status", "").strip() or "未读",
        "notes": form.get("notes", "").strip(),
    }


def form_values_from(book=None, form=None):
    """生成 book_form.html 需要回填的字段字典（新增 / 编辑 / 校验失败共用）。"""
    src = form if form is not None else (book or {})
    vals = {}
    for key in ["title", "subtitle", "author", "author_nationality", "series",
                "publisher", "isbn",
                "file_path", "file_format", "cover_path",
                "status", "notes"]:
        vals[key] = src.get(key, "") if src else ""
    # 出版年存的是数字（0 表示未知），回填时转字符串
    vals["publish_year"] = str(src.get("publish_year", "")) if (src and src.get("publish_year")) else ""
    vals["pages"] = str(src.get("pages", "")) if (src and src.get("pages")) else ""
    vals["rating"] = str(src.get("rating", 0)) if src else "0"
    vals["series_number"] = str(src.get("series_number", "")) if src else ""
    if form is not None:
        vals["tags_str"] = form.get("tags", "")
    else:
        vals["tags_str"] = ", ".join((book or {}).get("tags", []))
    return vals


# ---------------------------------------------------------------------------
# Jinja 全局辅助（供模板直接调用）
# ---------------------------------------------------------------------------

def cover_url(book):
    """
    返回书籍封面可访问 URL：优先真实封面，缺失时回退内置占位图。
    兼容性（换电脑可移植）：cover_path 可能是
      - http(s) 外链
      - 仅文件名（如 cover_xxx.jpg）或相对路径 covers/xxx.jpg
      - 旧数据的本机绝对路径
    统一提取文件名，若 static/covers 下存在则走静态路由（与机器路径无关）。
    """
    path = (book or {}).get("cover_path", "")
    if not path:
        return url_for("static", filename="images/default_cover.svg")
    if path.startswith(("http://", "https://")):
        return path
    # 统一提取文件名（兼容绝对 / 相对 / 纯文件名，Windows/Unix 分隔符）
    basename = os.path.basename(path.replace("\\", "/"))
    if basename:
        candidate = os.path.join(COVER_UPLOAD_DIR, basename)
        if os.path.isfile(candidate):
            return url_for("static", filename="covers/" + basename)
    # 兼容：旧数据绝对路径仍可用（本机）
    if os.path.isfile(path):
        covers_prefix = os.path.abspath(COVER_UPLOAD_DIR) + os.sep
        if os.path.abspath(path).startswith(covers_prefix):
            rel = os.path.relpath(path, os.path.join(BASE_DIR, "static"))
            return url_for("static", filename=rel.replace(os.sep, "/"))
        return url_for("serve_file", filepath=path)
    return url_for("static", filename="images/default_cover.svg")


def status_class(status):
    """阅读状态 → Bootstrap 徽章样式类。"""
    return {"未读": "secondary", "在读": "primary",
            "已读": "success", "搁置": "warning"}.get(status, "secondary")


def file_exists(path):
    """判断书籍文件路径在磁盘上是否存在。"""
    return bool(path) and os.path.exists(path)


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

def _ensure_shelves(data):
    """确保 data 含 shelves 键（兼容旧库）。"""
    return data.setdefault("shelves", [])


def shelf_members(shelf, books):
    """返回书架内的书籍列表（普通=按 book_ids 顺序；智能=按规则实时筛选）。"""
    if shelf.get("kind") == "smart":
        rule = shelf.get("rule") or {}
        tags = set(rule.get("tags") or [])
        status = (rule.get("status") or "").strip()
        author = (rule.get("author") or "").strip()
        series = (rule.get("series") or "").strip()
        rating = safe_num(rule.get("rating"), 0)
        out = []
        for b in books:
            if tags and not (tags & set(b.get("tags", []))):
                continue
            if status and b.get("status") != status:
                continue
            if author and (b.get("author") or "") != author:
                continue
            if series and (b.get("series") or "") != series:
                continue
            if rating and safe_num(b.get("rating")) != rating:
                continue
            out.append(b)
        return out
    by_id = {b["book_id"]: b for b in books}
    return [by_id[i] for i in shelf.get("book_ids", []) if i in by_id]


def shelf_rule_text(shelf):
    """把智能书架规则转成可读中文描述。"""
    rule = shelf.get("rule") or {}
    parts = []
    if rule.get("tags"):
        parts.append("标签含 " + "、".join(rule["tags"]))
    if rule.get("status"):
        parts.append("状态=" + rule["status"])
    if rule.get("author"):
        parts.append("作者=" + rule["author"])
    if rule.get("series"):
        parts.append("丛书=" + rule["series"])
    if safe_num(rule.get("rating"), 0):
        parts.append("评分≥" + str(rule["rating"]))
    return " 且 ".join(parts) if parts else "（空规则，暂不含任何书）"


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


def _tag_stats(data):
    """标签统计数据（供「工具合集」页展示）：按数量降序。"""
    counts = {}
    for b in data["books"]:
        for t in b.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return {"top": top, "total_tags": len(top),
            "total_books": len(data["books"]),
            "max_count": (top[0][1] if top else 1)}


def _count_nationalities(data):
    """统计各国籍书籍数量（有国籍的书），按数量降序。"""
    counts = {}
    for b in data["books"]:
        n = (b.get("author_nationality") or "").strip()
        if n:
            counts[n] = counts.get(n, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _nat_stats(data):
    """作者国籍汇总数据（供「工具合集」页展示）。"""
    books = data["books"]
    with_author = [b for b in books if b.get("author")]
    filled = [b for b in with_author
              if (b.get("author_nationality") or "").strip()]
    return {"total": len(books), "with_author": len(with_author),
            "filled": len(filled),
            "pending": len(with_author) - len(filled),
            "counts": _count_nationalities(data)}


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
