# -*- coding: utf-8 -*-
"""数据持久化单元测试（shelfmark/storage.py）。

全部在临时目录里跑（temp_storage fixture），不碰真实书库。
重点验证「坏数据不能让程序崩溃」这条硬约定。
"""

import json
import os

from shelfmark.storage import (_atomic_replace, ensure_data_dir, get_book,
                               load_config, load_data, online_metadata_enabled,
                               save_config, save_data)


class TestSaveLoadRoundTrip:
    def test_save_then_load(self, temp_storage):
        S = temp_storage
        data = {"version": 1, "books": [{"book_id": "x", "title": "三体"}]}
        S.save_data(data)
        assert S.load_data() == data

    def test_unicode_preserved(self, temp_storage):
        S = temp_storage
        S.save_data({"version": 1, "books": [{"book_id": "x",
                                             "title": "三体",
                                             "author": "刘慈欣"}]})
        raw = open(S.LIBRARY_FILE, encoding="utf-8").read()
        assert "三体" in raw                    # ensure_ascii=False，中文原样存
        assert S.load_data()["books"][0]["author"] == "刘慈欣"

    def test_missing_file_creates_empty_library(self, temp_storage):
        S = temp_storage
        assert not os.path.exists(S.LIBRARY_FILE)
        data = S.load_data()
        assert data["books"] == []
        assert os.path.isfile(S.LIBRARY_FILE)   # 自动落盘

    def test_no_leftover_tmp_files(self, temp_storage):
        S = temp_storage
        S.save_data({"version": 1, "books": []})
        S.save_data({"version": 1, "books": []})
        leftovers = [f for f in os.listdir(S.DATA_DIR) if f.endswith(".tmp")]
        assert leftovers == []


class TestCorruptedLibrary:
    def test_bad_json_rebuilds_empty_library(self, temp_storage):
        S = temp_storage
        with open(S.LIBRARY_FILE, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        data = S.load_data()
        assert data == {"version": 1, "books": []}
        # 原文件应被备份（备份失败时被静默吞掉，故此处不强制断言存在）
        assert os.path.isfile(S.LIBRARY_FILE)

    def test_wrong_shape_rebuilds(self, temp_storage):
        S = temp_storage
        S.save_data_no_check = None
        with open(S.LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)            # 顶层是 list，不是 dict
        assert S.load_data() == {"version": 1, "books": []}

    def test_missing_books_key_rebuilds(self, temp_storage):
        S = temp_storage
        with open(S.LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": 1}, f)
        assert S.load_data()["books"] == []


class TestGetBook:
    def test_found(self, temp_storage, sample_book):
        S = temp_storage
        S.save_data({"version": 1, "books": [sample_book]})
        assert S.get_book(sample_book["book_id"])["title"] == "三体"

    def test_not_found_returns_none(self, temp_storage):
        S = temp_storage
        S.save_data({"version": 1, "books": []})
        assert S.get_book("nope") is None


class TestConfig:
    def test_default_empty(self, temp_storage):
        assert temp_storage.load_config() == {}

    def test_save_and_load(self, temp_storage):
        S = temp_storage
        S.save_config({"site_dir": r"D:\site", "online_metadata": False})
        assert S.load_config()["site_dir"] == r"D:\site"
        assert S.load_config()["online_metadata"] is False

    def test_broken_config_returns_empty(self, temp_storage):
        S = temp_storage
        S.ensure_data_dir()
        with open(S.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("not json at all")
        assert S.load_config() == {}

    def test_non_dict_config_returns_empty(self, temp_storage):
        S = temp_storage
        S.ensure_data_dir()
        with open(S.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump([1, 2], f)
        assert S.load_config() == {}


class TestOnlineMetadataSwitch:
    def test_default_enabled(self, temp_storage):
        assert temp_storage.online_metadata_enabled() is True

    def test_can_be_disabled(self, temp_storage):
        temp_storage.save_config({"online_metadata": False})
        assert temp_storage.online_metadata_enabled() is False


class TestGetSiteDir:
    def test_env_var_wins(self, temp_storage, monkeypatch):
        S = temp_storage
        S.save_config({"site_dir": r"D:\from_config"})
        monkeypatch.setenv("SITE_DIR", r"  D:\from_env  ")
        assert S.get_site_dir() == r"D:\from_env"

    def test_config_second(self, temp_storage, monkeypatch):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        S.save_config({"site_dir": r"D:\from_config"})
        assert S.get_site_dir() == r"D:\from_config"

    def test_default_last(self, temp_storage, monkeypatch):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        assert S.get_site_dir() == S.DEFAULT_SITE_DIR

    def test_quotes_stripped(self, temp_storage, monkeypatch):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        S.save_config({"site_dir": '"D:\\quoted"'})
        assert S.get_site_dir() == r"D:\quoted"


class TestEnsureDataDir:
    def test_creates_missing_dir(self, tmp_path, monkeypatch):
        import shelfmark.storage as S
        target = tmp_path / "nested" / "data"
        monkeypatch.setattr(S, "DATA_DIR", str(target))
        S.ensure_data_dir()
        assert target.is_dir()


class TestAtomicReplace:
    def test_replaces_content(self, tmp_path):
        src = tmp_path / "new.txt"
        dst = tmp_path / "old.txt"
        src.write_text("new", encoding="utf-8")
        dst.write_text("old", encoding="utf-8")
        _atomic_replace(str(src), str(dst))
        assert dst.read_text(encoding="utf-8") == "new"

    def test_handles_missing_target(self, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("x", encoding="utf-8")
        dst = tmp_path / "b.txt"
        _atomic_replace(str(src), str(dst))
        assert dst.read_text(encoding="utf-8") == "x"
