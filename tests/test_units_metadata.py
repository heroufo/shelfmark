# -*- coding: utf-8 -*-
"""在线元数据模块单元测试（shelfmark/metadata.py）。

**全部离线**：解析逻辑用固定 HTML 片段喂进去，抓取函数只验证
「离线开关生效」「网络失败优雅返回」，绝不发真实请求。
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


import pytest

from shelfmark.metadata import (_fetch_meta_by_title, _parse_subject_info,
                                fetch_book_meta)

SAMPLE_HTML = """
<html><body>
<div id="info">
<span class="pl">作者</span>: [中] 刘慈欣<br/>
<span class="pl">出版社</span>: 重庆出版社<br/>
<span class="pl">出版年</span>: 2008-1-1<br/>
<span class="pl">页数</span>: 302<br/>
<span class="pl">定价</span>: 23.00元<br/>
</div>
</body></html>
"""

FOREIGN_HTML = """
<div id="info">
<span class="pl">作者</span>: [挪] 格德·布兰腾伯格 著<br/>
<span class="pl">出版社</span>: 上海文艺出版社<br/>
<span class="pl">出版年</span>: 2019<br/>
<span class="pl">页数</span>: 410页<br/>
</div>
"""

PARTIAL_HTML = """
<div id="info">
<span class="pl">出版社</span>: 某社<br/>
</div>
"""


class TestParseSubjectInfo:
    def test_full_record(self):
        meta = _parse_subject_info(SAMPLE_HTML)
        assert meta["author"] == "刘慈欣"
        assert meta["author_nationality"] == "中国"
        assert meta["publisher"] == "重庆出版社"
        assert meta["publish_year"] == "2008"
        assert meta["pages"] == "302"

    def test_foreign_author_nationality(self):
        meta = _parse_subject_info(FOREIGN_HTML)
        assert meta["author"] == "格德·布兰腾伯格"      # [挪] 与「著」被清掉
        assert meta["author_nationality"] == "挪威"
        assert meta["publisher"] == "上海文艺出版社"
        assert meta["publish_year"] == "2019"
        assert meta["pages"] == "410"                  # 「410页」取数字

    def test_partial_record_leaves_others_empty(self):
        meta = _parse_subject_info(PARTIAL_HTML)
        assert meta["publisher"] == "某社"
        assert meta["author"] == ""
        assert meta["pages"] == ""

    def test_no_info_block_returns_none(self):
        assert _parse_subject_info("<html><body>无内容</body></html>") is None

    def test_empty_html_returns_none(self):
        assert _parse_subject_info("") is None

    def test_never_raises(self):
        for bad in ("<div id='info'>", "<div id=\"info\"></div>", "x" * 5000):
            _parse_subject_info(bad)      # 不抛异常即算通过


class TestOfflineSwitch:
    """data/config.json 里 online_metadata=false 时，所有抓取必须立即短路。"""

    def test_isbn_lookup_short_circuits(self, temp_storage):
        temp_storage.save_config({"online_metadata": False})
        assert fetch_book_meta("9787536692930") is None

    def test_title_lookup_short_circuits(self, temp_storage):
        temp_storage.save_config({"online_metadata": False})
        assert _fetch_meta_by_title("三体") is None

    def test_enabled_by_default(self, temp_storage):
        assert temp_storage.online_metadata_enabled() is True


class TestNetworkFailureIsGraceful:
    """网络不可达时的行为契约。

    _http_get_text 的设计就是「失败抛异常、由调用方兜底」（见其 docstring），
    因此这里验证的是：抛出的必须是网络类异常，而**不能是编程错误**
    （NameError / AttributeError 等重构事故的典型症状）。
    """

    def test_unreachable_host_raises_network_error_not_programming_error(self):
        import shelfmark.metadata as M
        try:
            M._http_get_text("http://127.0.0.1:1/x", timeout=0.3)
        except (NameError, AttributeError, TypeError, ImportError) as e:
            pytest.fail("抓取层出现编程错误（疑似重构事故）：%r" % e)
        except Exception:
            pass                     # 网络类异常属预期，由上层兜底

    def test_bad_input_returns_none_without_network(self, temp_storage):
        # 空 ISBN 必须在发请求之前就返回 None
        assert fetch_book_meta("") is None
        assert fetch_book_meta(None) is None
