# -*- coding: utf-8 -*-
"""书籍领域逻辑单元测试（shelfmark/books.py）。

覆盖：排序配置、表单校验与构建、书架成员计算、标签统计。
不涉及网络与真实书库。
"""

import pytest

from shelfmark.books import (LEGACY_SORT, SORTABLE_FIELDS, _ensure_shelves,
                             _tag_stats, build_book_from_form, cover_url,
                             form_values_from, recommend_related,
                             shelf_members, shelf_rule_text,
                             validate_book_form)


class TestSortableFields:
    def test_contains_documented_fields(self):
        for field in ("title", "author", "series", "publisher",
                      "publish_year", "rating", "pages", "status",
                      "file_format", "added_time"):
            assert field in SORTABLE_FIELDS, field

    def test_pages_sorts_numerically(self):
        key = SORTABLE_FIELDS["pages"]
        assert key({"pages": "302"}) == 302
        assert key({"pages": 0}) == 0
        assert key({}) == 0

    def test_title_is_case_insensitive(self):
        key = SORTABLE_FIELDS["title"]
        assert key({"title": "abc"}) == key({"title": "ABC"})

    def test_series_key_is_tuple_with_fallback(self):
        key = SORTABLE_FIELDS["series"]
        assert key({"series": "A", "series_number": "2"}) == ("a", 2)
        assert key({"series": "A"}) == ("a", 10 ** 9)

    def test_legacy_sort_map(self):
        for legacy, modern in LEGACY_SORT.items():
            field, _, direction = modern.partition(":")
            assert field in SORTABLE_FIELDS, legacy
            assert direction in ("asc", "desc")


class TestValidateBookForm:
    def test_ok(self):
        assert validate_book_form({"title": "书名"}) is None

    def test_missing_title(self):
        assert validate_book_form({"title": ""}) is not None
        assert validate_book_form({"title": "   "}) is not None
        assert validate_book_form({}) is not None

    def test_missing_series_number_when_series_empty_is_ok(self):
        assert validate_book_form({"title": "x", "series": "", "series_number": ""}) is None

    def test_series_with_series_number(self):
        assert validate_book_form({"title": "x", "series": "丛书", "series_number": "2"}) is None

    def test_number_field_rejects_garbage(self):
        bad = {"title": "x", "series": "丛书", "series_number": "第二卷"}
        assert validate_book_form(bad) is not None


class TestBuildBookFromForm:
    def test_basic_fields(self):
        b = build_book_from_form({
            "title": " 三体 ", "author": "刘慈欣", "publisher": "重庆出版社",
            "publish_year": "2008", "pages": "302", "rating": "5",
            "tags": "科幻, 文学", "isbn": "9787536692930",
            "file_format": "pdf", "status": "已读",
        })
        assert b["title"] == "三体"                 # 首尾空白被清掉
        assert b["publish_year"] == 2008
        assert b["pages"] == 302
        assert b["rating"] == 5
        assert b["tags"] == ["科幻", "文学"]
        assert b["status"] == "已读"

    def test_defaults(self):
        b = build_book_from_form({"title": "x"})
        assert b["status"] == "未读"
        assert b["pages"] == 0
        assert b["rating"] == 0
        assert b["publish_year"] == 0
        assert b["series_number"] == 0
        assert b["tags"] == []

    def test_pages_defaults_to_zero_when_garbage(self):
        assert build_book_from_form({"title": "x", "pages": "未知"})["pages"] == 0

    def test_nationality_from_explicit_field_wins(self):
        b = build_book_from_form({"title": "x", "author_nationality": "法国",
                                  "file_path": r"D:\[英]某人.pdf"})
        assert b["author_nationality"] == "法国"

    def test_nationality_falls_back_to_filename(self):
        b = build_book_from_form({"title": "x", "author_nationality": "",
                                  "file_path": r"D:\[英]阿加莎.pdf"})
        assert b["author_nationality"] == "英国"

    def test_nationality_defaults_to_china(self):
        b = build_book_from_form({"title": "x", "file_path": "三体.pdf"})
        assert b["author_nationality"] == "中国"

    def test_format_guessed_from_path(self):
        b = build_book_from_form({"title": "x", "file_path": "a/b/c.epub"})
        assert b["file_format"] == "epub"


class TestFormValuesFrom:
    def test_from_book(self, sample_book):
        v = form_values_from(book=sample_book)
        assert v["title"] == "三体"
        assert v["publish_year"] == "2008"          # 数字转字符串回填
        assert v["pages"] == "302"
        assert v["rating"] == "5"
        assert "科幻" in v["tags_str"]

    def test_zero_year_renders_empty(self):
        v = form_values_from(book={"title": "x", "publish_year": 0, "pages": 0})
        assert v["publish_year"] == ""
        assert v["pages"] == ""

    def test_from_form_keeps_raw_tags(self):
        v = form_values_from(form={"title": "x", "tags": "a, b"})
        assert v["tags_str"] == "a, b"

    def test_empty_input_is_safe(self):
        v = form_values_from(book=None, form=None)
        assert v["title"] == ""
        assert v["tags_str"] == ""


class TestShelves:
    def test_ensure_shelves_creates_key(self):
        data = {"books": []}
        assert _ensure_shelves(data) == []
        assert "shelves" in data

    def test_normal_shelf_follows_book_ids_order(self):
        books = [{"book_id": "a", "title": "A"}, {"book_id": "b", "title": "B"}]
        shelf = {"kind": "normal", "book_ids": ["b", "a", "missing"]}
        assert [x["book_id"] for x in shelf_members(shelf, books)] == ["b", "a"]

    def test_smart_shelf_filters_by_rules(self):
        books = [
            {"book_id": "1", "tags": ["科幻"], "status": "已读", "rating": 5},
            {"book_id": "2", "tags": ["科幻"], "status": "未读", "rating": 3},
            {"book_id": "3", "tags": ["历史"], "status": "已读", "rating": 5},
        ]
        shelf = {"kind": "smart", "rule": {"tags": ["科幻"], "status": "已读"}}
        assert [x["book_id"] for x in shelf_members(shelf, books)] == ["1"]

    def test_smart_shelf_empty_rule_matches_all(self):
        books = [{"book_id": "1"}, {"book_id": "2"}]
        assert len(shelf_members({"kind": "smart", "rule": {}}, books)) == 2

    def test_shelf_rule_text_readable(self):
        t = shelf_rule_text({"rule": {"tags": ["科幻", "文学"], "status": "已读",
                                      "rating": 4}})
        assert "科幻、文学" in t and "已读" in t and "评分≥4" in t

    def test_shelf_rule_text_empty(self):
        assert "空规则" in shelf_rule_text({"rule": {}})


class TestTagStats:
    def test_counts_sorted_by_frequency(self):
        data = {"books": [
            {"tags": ["a", "b"]}, {"tags": ["a"]}, {"tags": ["a", "c"]}, {}]}
        st = _tag_stats(data)
        assert st["top"][0] == ("a", 3)
        assert st["total_tags"] == 3
        assert st["total_books"] == 4

    def test_empty(self):
        st = _tag_stats({"books": []})
        assert st["top"] == [] and st["max_count"] == 1


class TestCoverUrl:
    def test_falls_back_to_placeholder(self, app_module):
        with app_module.app.test_request_context("/"):
            url = cover_url({"cover_path": ""})
        assert "default_cover.svg" in url

    def test_external_url_passthrough(self, app_module):
        with app_module.app.test_request_context("/"):
            url = cover_url({"cover_path": "https://x.test/a.jpg"})
        assert url == "https://x.test/a.jpg"

    def test_missing_local_file_falls_back(self, app_module):
        with app_module.app.test_request_context("/"):
            url = cover_url({"cover_path": "nonexistent_cover_xyz.jpg"})
        assert "default_cover.svg" in url


class TestRecommendRelated:
    def test_returns_books_sharing_features(self, sample_book):
        other = dict(sample_book, book_id="c" * 32, title="球状闪电")
        unrelated = dict(sample_book, book_id="d" * 32, title="完全无关",
                         tags=[], series="", author="别人", publisher="别社")
        out = recommend_related(sample_book, [sample_book, other, unrelated], 5)
        assert isinstance(out, list)
        assert all(b["book_id"] != sample_book["book_id"] for b in out)

    def test_handles_empty_library(self, sample_book):
        assert recommend_related(sample_book, [], 5) == []
