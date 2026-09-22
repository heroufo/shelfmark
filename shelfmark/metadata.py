# -*- coding: utf-8 -*-
"""在线元数据获取（数据源：豆瓣）。

仅用于补全书籍元数据（作者/国籍/出版社/出版年/页数/简介），
**只填空字段、不覆盖已有值**。可通过 data/config.json 的
online_metadata=false 完全关闭（见 storage.online_metadata_enabled），
关闭后所有抓取入口立即短路、不发任何网络请求。"""

import json
import re
import ssl
import time
import urllib.parse
import urllib.request

from shelfmark.nationality import _parse_nationality
from shelfmark.storage import (
    get_book,
    load_data,
    online_metadata_enabled,
    save_data,
)
from shelfmark.utils import _strip_html, _truncate_cn


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
