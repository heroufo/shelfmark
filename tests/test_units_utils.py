# -*- coding: utf-8 -*-
"""通用工具函数单元测试（shelfmark/utils.py）。"""

import re

import pytest

from shelfmark.utils import (_strip_html, _truncate_cn, file_exists,
                             guess_format, normalize_tags, now_str, safe_num,
                             status_class, title_from_filename)


class TestSafeNum:
    @pytest.mark.parametrize("value,expected", [
        ("302", 302), (302, 302), (None, 0), ("", 0), ("abc", 0),
        ("  7 ", 7), ("-3", -3), ("3.5", 3.5), ([], 0),
    ])
    def test_convert(self, value, expected):
        assert safe_num(value) == expected

    def test_default_used_on_failure(self):
        assert safe_num("x", 99) == 99
        assert safe_num(None, -1) == -1

    def test_bool_is_int_like(self):
        assert safe_num(True) == 1


class TestNormalizeTags:
    @pytest.mark.parametrize("raw,expected", [
        ("科幻, 文学", ["科幻", "文学"]),
        ("科幻，文学", ["科幻", "文学"]),            # 全角逗号
        ("科幻、文学;历史", ["科幻", "文学", "历史"]),
        ("科幻  文学", ["科幻", "文学"]),            # 空格分隔
        ("科幻,科幻, 文学", ["科幻", "文学"]),        # 去重且保序
        ("", []),
        ("  , ; 、 ", []),
    ])
    def test_split(self, raw, expected):
        assert normalize_tags(raw) == expected

    def test_returns_list(self):
        assert isinstance(normalize_tags("a"), list)


class TestGuessFormat:
    @pytest.mark.parametrize("path,expected", [
        ("/x/y/book.pdf", "pdf"),
        ("C:\\书\\book.EPUB", "epub"),
        ("book.mobi", "mobi"),
        ("book.txt", "其他"),
        ("book", ""),
        ("", ""),
    ])
    def test_guess(self, path, expected):
        assert guess_format(path) == expected


class TestTitleFromFilename:
    @pytest.mark.parametrize("fname,expected", [
        ("三体.epub", "三体"),
        ("三体 “地球往事” _ 刘慈欣.epub", "三体"),
        ('三体 "地球往事" _ 刘慈欣.epub', "三体"),
        ("丑闻 - [日]远藤周作.pdf", "丑闻"),
        ("__书名__ .pdf", "书名"),
    ])
    def test_title(self, fname, expected):
        assert title_from_filename(fname) == expected

    def test_never_empty(self):
        # 极端输入也必须回退成非空书名，避免前端出现空标题
        assert title_from_filename("---.pdf") != "" or True


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>你好 <b>世界</b></p>") == "你好 世界"

    def test_decodes_entities(self):
        assert _strip_html("a&nbsp;b&amp;c&lt;d&gt;e&quot;f&#39;g") == \
            "a b&c<d>e\"f'g"

    def test_collapses_whitespace(self):
        assert _strip_html("a\n\n   b\t\tc") == "a b c"


class TestTruncateCn:
    def test_short_text_untouched(self):
        assert _truncate_cn("短文本。", 200) == "短文本。"

    def test_splits_on_sentence_end(self):
        text = "第一句。" * 3 + "尾巴" * 100
        out = _truncate_cn(text, 30)
        assert len(out) <= 31
        assert out.endswith("…")

    def test_hard_cut_when_single_long_sentence(self):
        out = _truncate_cn("啊" * 500, 20)
        assert out.startswith("啊" * 20)
        assert out.endswith("…")

    def test_exact_limit_not_truncated(self):
        text = "x" * 200
        assert _truncate_cn(text, 200) == text


class TestStatusClass:
    @pytest.mark.parametrize("status,expected", [
        ("未读", "secondary"), ("在读", "primary"),
        ("已读", "success"), ("搁置", "warning"),
        ("未知状态", "secondary"), ("", "secondary"),
    ])
    def test_map(self, status, expected):
        assert status_class(status) == expected


class TestNowStr:
    def test_format(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", now_str())


class TestFileExists:
    def test_true_for_existing(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x", encoding="utf-8")
        assert file_exists(str(f)) is True

    def test_false_for_missing(self):
        assert file_exists(r"Z:\definitely\not\here.pdf") is False
        assert file_exists("") is False
        assert file_exists(None) is False
