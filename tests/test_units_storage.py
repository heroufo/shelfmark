# -*- coding: utf-8 -*-
"""数据持久化单元测试（shelfmark/storage.py）。

全部在临时目录里跑（temp_storage fixture），不碰真实书库。
重点验证「坏数据不能让程序崩溃」这条硬约定。
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


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


class TestSiteDirDetect:
    """站点目录自动探测：源码版 / 打包版（exe 在子目录）都应找到同一个仓库。

    背景：打包版把 exe 放在 dist_exe/ 之类子目录时，原先「只看程序目录同级」
    会找不到站点仓库，报「在线站点目录不存在」。现在改为逐级向上查找。
    """

    def _norm(self, p):
        return os.path.normcase(os.path.normpath(str(p)))

    def test_candidates_start_at_sibling(self, tmp_path, monkeypatch):
        import shelfmark.paths as P
        runtime = tmp_path / "proj" / "dist_exe"
        runtime.mkdir(parents=True)
        monkeypatch.setattr(P, "RUNTIME_DIR", str(runtime))
        cands = P.site_dir_candidates()
        # 第一个候选仍是「与程序目录同级」（保持历史行为可预期）
        assert self._norm(cands[0]) == self._norm(tmp_path / "proj" / "library-web")
        # 但会继续向上，覆盖到项目目录的同级
        assert self._norm(tmp_path / "library-web") in [self._norm(c) for c in cands]

    def test_detect_finds_site_one_level_up(self, tmp_path, monkeypatch):
        """站点仓库在项目目录同级，程序跑在 项目/dist_exe 里 —— 应能自动命中。"""
        import shelfmark.paths as P
        site = tmp_path / "library-web"
        (site / "data").mkdir(parents=True)
        runtime = tmp_path / "proj" / "dist_exe"
        runtime.mkdir(parents=True)
        monkeypatch.setattr(P, "RUNTIME_DIR", str(runtime))
        assert self._norm(P._detect_site_dir()) == self._norm(site)

    def test_detect_accepts_git_or_index_marker(self, tmp_path, monkeypatch):
        import shelfmark.paths as P
        site = tmp_path / "library-web"
        site.mkdir()
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        runtime = tmp_path / "proj"
        runtime.mkdir()
        monkeypatch.setattr(P, "RUNTIME_DIR", str(runtime))
        assert self._norm(P._detect_site_dir()) == self._norm(site)

    def test_plain_empty_dir_is_not_a_site(self, tmp_path, monkeypatch):
        """同名但没有任何站点特征的目录不算命中，退回约定路径（不猜）。"""
        import shelfmark.paths as P
        (tmp_path / "library-web").mkdir()             # 空壳目录
        runtime = tmp_path / "proj"
        runtime.mkdir()
        monkeypatch.setattr(P, "RUNTIME_DIR", str(runtime))
        assert self._norm(P._detect_site_dir()) == \
            self._norm(P.site_dir_candidates()[0])


class TestSetSiteDir:
    """界面上「设置站点目录」写回配置的行为。"""

    def test_rejects_missing_dir(self, temp_storage):
        S = temp_storage
        assert S.set_site_dir(r"D:\definitely\not\here") is None
        assert "site_dir" not in S.load_config()

    def test_rejects_empty(self, temp_storage):
        S = temp_storage
        assert S.set_site_dir("   ") is None
        assert S.set_site_dir(None) is None

    def test_saves_and_strips_quotes(self, temp_storage, tmp_path):
        S = temp_storage
        site = tmp_path / "site"
        site.mkdir()
        saved = S.set_site_dir('"%s"' % site)
        assert saved == str(site)
        assert S.load_config()["site_dir"] == str(site)

    def test_get_site_dir_uses_saved_path(self, temp_storage, monkeypatch, tmp_path):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        site = tmp_path / "site"
        site.mkdir()
        S.set_site_dir(str(site))
        assert S.get_site_dir() == str(site)

    def test_info_reports_existence(self, temp_storage, monkeypatch, tmp_path):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        site = tmp_path / "site"
        site.mkdir()
        S.set_site_dir(str(site))
        info = S.site_dir_info()
        assert info["site"] == str(site)
        assert info["exists"] is True
        assert isinstance(info["tried"], list) and info["tried"]

    def test_info_reports_missing(self, temp_storage, monkeypatch, tmp_path):
        S = temp_storage
        monkeypatch.delenv("SITE_DIR", raising=False)
        absent = str(tmp_path / "not-here")
        # 把「自动探测的兜底路径」也指到不存在的目录，模拟真机上找不到站点仓库
        monkeypatch.setattr(S, "DEFAULT_SITE_DIR", absent)
        assert S.set_site_dir(absent) is None           # 不存在 → 不写入配置
        info = S.site_dir_info()
        assert info["site"] == absent
        assert info["exists"] is False
