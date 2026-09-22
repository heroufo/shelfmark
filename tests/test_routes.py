# -*- coding: utf-8 -*-
"""
路由表完整性测试（不需要书库数据，CI 必跑）。

这是重构的「防呆网」：
拆模块最危险的不是函数搬家，而是**端点名（endpoint）被改动**——
模板里的 url_for('index') 一旦对不上就会整站 500。
本文件把 36 条路由的「URL 规则 / 端点名 / 方法」全部固化为基线，
并反向扫描所有模板，确认每个 url_for 引用的端点都真实存在。
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")

# 基线路由表（重构前记录，任何改动都必须是有意的）
EXPECTED_ROUTES = [
    ("/", "index", ("GET",)),
    ("/all", "all_books", ("GET",)),
    ("/api/book_meta", "api_book_meta", ("GET",)),
    ("/api/browse_file", "api_browse_file", ("GET",)),
    ("/api/browse_folder", "api_browse_folder", ("GET",)),
    ("/api/upload_cover", "api_upload_cover", ("POST",)),
    ("/author/<path:author>", "author_view", ("GET",)),
    ("/book/<book_id>", "book_detail", ("GET",)),
    ("/book/<book_id>/douban_update", "book_douban_update", ("POST",)),
    ("/book/<book_id>/refresh_blurb", "refresh_blurb", ("GET",)),
    ("/book/add", "book_add", ("GET", "POST")),
    ("/book/bulk_delete", "book_bulk_delete", ("POST",)),
    ("/book/delete/<book_id>", "book_delete", ("POST",)),
    ("/book/edit/<book_id>", "book_edit", ("GET", "POST")),
    ("/books/bulk/shelf", "books_bulk_shelf", ("POST",)),
    ("/books/bulk/tags", "books_bulk_tags", ("POST",)),
    ("/download/<book_id>", "download_book", ("GET",)),
    ("/export", "export_json", ("GET",)),
    ("/file/<path:filepath>", "serve_file", ("GET",)),
    ("/import", "import_books", ("GET", "POST")),
    ("/import/commit", "import_commit", ("POST",)),
    ("/nationality/run", "nationality_run", ("POST",)),
    ("/open/<book_id>", "open_book", ("GET",)),
    ("/paths/run", "paths_repair", ("POST",)),
    ("/publish", "publish_online", ("POST",)),
    ("/publisher/<path:publisher>", "publisher_view", ("GET",)),
    ("/restore", "restore_json", ("POST",)),
    ("/series", "series_view", ("GET",)),
    ("/shelf/<shelf_id>", "shelf_detail", ("GET",)),
    ("/shelf/<shelf_id>/delete", "shelf_delete", ("POST",)),
    ("/shelf/<shelf_id>/edit", "shelf_edit", ("GET", "POST")),
    ("/shelf/<shelf_id>/remove", "shelf_remove_book", ("POST",)),
    ("/shelf/add", "shelf_add_book", ("POST",)),
    ("/shelf/create", "shelf_create", ("POST",)),
    ("/shelves", "shelves_view", ("GET",)),
    ("/stats", "stats_view", ("GET",)),
]


def app_routes(app):
    out = []
    for r in app.url_map.iter_rules():
        if str(r).startswith("/static"):
            continue
        out.append((str(r), r.endpoint,
                    tuple(sorted(r.methods - {"HEAD", "OPTIONS"}))))
    return sorted(out)


class TestRouteTable:
    def test_route_count(self, app_module):
        assert len(app_routes(app_module.app)) == len(EXPECTED_ROUTES)

    def test_exact_match(self, app_module):
        actual = app_routes(app_module.app)
        expected = sorted(EXPECTED_ROUTES)
        missing = [r for r in expected if r not in actual]
        extra = [r for r in actual if r not in expected]
        assert not missing, "路由缺失：%s" % missing
        assert not extra, "出现未预期路由：%s" % extra

    def test_endpoints_unique(self, app_module):
        eps = [r.endpoint for r in app_module.app.url_map.iter_rules()
               if not str(r).startswith("/static")]
        assert len(eps) == len(set(eps))

    @pytest.mark.parametrize("name", [
        "index", "all_books", "book_detail", "book_add", "book_edit",
        "book_delete", "shelves_view", "shelf_detail", "stats_view",
        "import_books", "import_commit", "export_json", "restore_json",
        "publish_online", "series_view", "author_view", "publisher_view",
        "serve_file", "api_browse_file", "api_browse_folder",
        "api_book_meta", "api_upload_cover", "download_book",
        "refresh_blurb", "book_douban_update", "books_bulk_tags",
        "books_bulk_shelf", "paths_repair", "nationality_run", "open_book",
    ])
    def test_endpoint_exists(self, app_module, name):
        assert any(r.endpoint == name for r in app_module.app.url_map.iter_rules())


class TestTemplatesUrlFor:
    """模板里 url_for 引用的端点必须全部存在（含变量端点的白名单）。"""

    # 模板中以变量形式传入的端点名（无法静态解析，逐个人工确认）
    DYNAMIC_ALLOWED = {"list_endpoint"}

    def _scan(self):
        refs = {}
        if not os.path.isdir(TEMPLATES):
            return refs
        for fn in sorted(os.listdir(TEMPLATES)):
            if not fn.endswith(".html"):
                continue
            with open(os.path.join(TEMPLATES, fn), encoding="utf-8") as f:
                text = f.read()
            for name in re.findall(r"url_for\(\s*['\"]([^'\"]+)['\"]", text):
                refs.setdefault(name, []).append(fn)
        return refs

    def test_no_unknown_endpoint(self, app_module):
        known = {r.endpoint for r in app_module.app.url_map.iter_rules()}
        known |= {"static", "serve_file"}
        unknown = {n: f for n, f in self._scan().items()
                   if n not in known and n not in self.DYNAMIC_ALLOWED}
        assert not unknown, "模板引用了不存在的端点：%s" % unknown

    def test_templates_actually_reference_something(self):
        # 防止正则失效导致上一条测试变成「永远通过」
        refs = self._scan()
        assert len(refs) >= 5, "模板 url_for 扫描结果异常：%s" % list(refs)


class TestViewModulesRegistered:
    """每个视图模块都必须真的把路由注册进来了（防止漏调 register）。"""

    @pytest.mark.parametrize("module_name,min_routes", [
        ("system", 3),      # 3 个 context processor
        ("browse", 6),
        ("books", 10),
        ("shelves", 7),
        ("tools", 8),
        ("api", 5),
    ])
    def test_module_contributes_routes(self, app_module, module_name,
                                       min_routes):
        import importlib

        mod = importlib.import_module("shelfmark.views." + module_name)
        captured = []

        class FakeApp:
            def add_url_rule(self, rule, endpoint=None, view_func=None, **kw):
                captured.append(endpoint)

            def context_processor(self, fn):
                captured.append("ctx:" + fn.__name__)

        mod.register(FakeApp())
        assert len(captured) >= min_routes, \
            "%s 只注册了 %d 项" % (module_name, len(captured))
