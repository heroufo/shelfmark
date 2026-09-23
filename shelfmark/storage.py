# -*- coding: utf-8 -*-
"""书库元数据持久化：加载、原子保存、配置读写、站点目录解析。

保存采用四级兜底链（见 _atomic_replace），兼容受限文件系统：
  ① os.replace 重试 → ② copy2 复制覆盖 → ③ 备份后重建 → ④ .recover + 报错
损坏的数据文件会自动备份为 .bak 并重建空库，不让程序崩溃。"""

import json
import os
import shutil
import time
import uuid

from shelfmark.paths import (
    CONFIG_FILE,
    DATA_DIR,
    DEFAULT_SITE_DIR,
    LIBRARY_FILE,
    site_dir_candidates,
)


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
      环境变量 SITE_DIR > data/config.json 的 site_dir 字段 > 自动探测的默认路径。
    自动探测见 paths.py：从程序目录逐级向上找同级的 library-web，源码版 / 打包版都能命中，
    支持换电脑后把站点仓库路径写入 data/config.json 即可发布，无需改代码。
    """
    env = os.environ.get("SITE_DIR")
    if env:
        return _clean_path(env)
    site = (load_config().get("site_dir") or DEFAULT_SITE_DIR)
    return _clean_path(site)


def _clean_path(p):
    """去掉用户粘贴路径时常见的首尾空白与成对引号。"""
    return (p or "").strip().strip('"').strip("'")


def set_site_dir(path):
    """
    把在线站点目录写进 data/config.json（site_dir 字段），供界面上一键指定。
    只接受确实存在的目录；成功返回清洗后的路径，失败返回 None（不改动配置）。
    """
    p = _clean_path(path)
    if not p or not os.path.isdir(p):
        return None
    cfg = load_config()
    cfg["site_dir"] = p
    save_config(cfg)
    return p


def site_dir_info():
    """供界面展示：当前解析到的站点目录，以及它是否真实存在。"""
    site = get_site_dir()
    return {
        "site": site,
        "exists": os.path.isdir(site),
        "tried": site_dir_candidates(),
    }


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
