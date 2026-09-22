# -*- coding: utf-8 -*-
"""
pytest 公共装置。

要点：
1. 把项目根加进 sys.path，使 app.py 与 shelfmark 包可被导入；
2. 单元测试一律在临时目录里跑（tmp_path），**绝不碰真实书库**；
3. 需要真实书库的测试用 skipif 标记，缺失数据时自动跳过（便于在 CI 运行）。

测试分层：
    test_units_*.py    纯函数与隔离数据存储（无外部依赖，CI 必跑）
    test_routes.py     路由表完整性：端点名与 URL 规则（CI 必跑）
    regression_reallib.py / post_routes_check.py   本机真实书库端到端脚本
    manual_*.py        需要真人点击的手动验证脚本（pytest 不收集）
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REAL_LIBRARY = os.path.join(ROOT, "data", "library.json")
requires_real_library = pytest.mark.skipif(
    not os.path.isfile(REAL_LIBRARY),
    reason="需要本机真实书库 data/library.json（CI 上会跳过）")


@pytest.fixture(scope="session")
def app_module():
    """导入应用模块（只创建 Flask 对象并注册路由，不读写书库数据）。"""
    import app
    return app


@pytest.fixture()
def temp_storage(tmp_path, monkeypatch):
    """把存储层指向临时目录，隔离出可随意读写的「影子书库」。

    注意：只改 shelfmark.storage 模块内的全局常量即可生效——所有读写函数
    都在该模块的命名空间里查找 LIBRARY_FILE / DATA_DIR。
    """
    import shelfmark.storage as S

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(S, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(S, "LIBRARY_FILE", str(data_dir / "library.json"))
    monkeypatch.setattr(S, "CONFIG_FILE", str(data_dir / "config.json"))
    return S


@pytest.fixture()
def sample_book():
    """一条结构完整的书籍记录（测试用，字段与真实数据一致）。"""
    return {
        "book_id": "b" * 32,
        "title": "三体",
        "subtitle": "地球往事",
        "author": "刘慈欣",
        "author_nationality": "中国",
        "series": "地球往事",
        "series_number": 1,
        "publisher": "重庆出版社",
        "publish_year": 2008,
        "pages": 302,
        "isbn": "9787536692930",
        "file_path": r"D:\书库\[中]刘慈欣 - 三体.pdf",
        "file_format": "pdf",
        "cover_path": "",
        "rating": 5,
        "tags": ["科幻", "中国文学"],
        "status": "已读",
        "blurb": "",
        "notes": "",
        "added_time": "2026-01-01 10:00:00",
    }
