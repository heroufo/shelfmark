# -*- coding: utf-8 -*-
"""作者国籍判定单元测试（shelfmark/nationality.py）。

该功能的关键约定：国籍只从文件名解析、不联网；无标记或标记无法识别一律
判定为中国。这些用例把这个约定固化下来。
"""

import pytest

from shelfmark.nationality import (_count_nationalities, _nat_stats,
                                   _parse_nationality,
                                   nationality_from_filename)


class TestNationalityFromFilename:
    @pytest.mark.parametrize("path,expected", [
        # 常见单字缩写
        (r"D:\书库\[英]阿加莎·克里斯蒂 - 东方快车谋杀案.pdf", "英国"),
        (r"D:\书库\[美]海明威 - 老人与海.epub", "美国"),
        ("[法]雨果 - 悲惨世界.pdf", "法国"),
        ("[日]东野圭吾 - 白夜行.mobi", "日本"),
        # 多字国名必须优先于单字匹配
        ("[印度尼西亚]普拉姆迪亚.pdf", "印度尼西亚"),
        ("[澳大利亚]考琳·麦卡洛.pdf", "澳大利亚"),
        ("[南非]库切.pdf", "南非"),
        # 无标记 / 无法识别 → 中国
        ("三体.epub", "中国"),
        ("[火星]某人.pdf", "中国"),
        ("", "中国"),
        (None, "中国"),
        # 目录名里的标记不参与判断（只看文件名）
        (r"D:\[美]某作者\[英]某作者\无标记书名.pdf", "中国"),
        # 反斜杠 / 正斜杠路径都要能取到 basename
        ("D:/书库/[德]歌德 - 浮士德.pdf", "德国"),
    ])
    def test_parse(self, path, expected):
        assert nationality_from_filename(path) == expected

    def test_never_raises_on_weird_input(self):
        for bad in (123, [], {"a": 1}, "\x00[英]"):
            assert isinstance(nationality_from_filename(bad), str)


class TestParseNationalityFromAuthorLine:
    @pytest.mark.parametrize("line,expected", [
        ("[挪] 格德·布兰腾伯格 著", "挪威"),
        ("[英] 阿加莎·克里斯蒂", "英国"),
        ("刘慈欣 著", ""),                 # 无标记 → 空（与文件名规则不同）
        ("", ""),
    ])
    def test_parse(self, line, expected):
        assert _parse_nationality(line) == expected


class TestCountNationalities:
    def test_counts_and_sorts_desc(self):
        data = {"books": [
            {"author_nationality": "中国"},
            {"author_nationality": "英国"},
            {"author_nationality": "中国"},
            {"author_nationality": "中国"},
            {"author_nationality": ""},
            {},
        ]}
        assert _count_nationalities(data) == [("中国", 3), ("英国", 1)]

    def test_empty_library(self):
        assert _count_nationalities({"books": []}) == []


class TestNatStats:
    def test_summary_numbers(self):
        data = {"books": [
            {"author": "A", "author_nationality": "中国"},
            {"author": "B", "author_nationality": ""},
            {"author": "", "author_nationality": ""},        # 无作者，不计入待补
            {"author": "D"},
        ]}
        st = _nat_stats(data)
        assert st["total"] == 4
        assert st["with_author"] == 3
        assert st["filled"] == 1
        assert st["pending"] == 2
        assert st["counts"] == [("中国", 1)]
