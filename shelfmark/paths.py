# -*- coding: utf-8 -*-
"""运行模式、目录常量与全局配置项。

本模块是「双基地」设计的落点：
  - 打包版（PyInstaller onefile）：RUNTIME_DIR = exe 所在目录（可写数据区），
    RES_DIR = exe 内部解压区（只读内置资源）
  - 源码版：两者都指向项目目录，行为与原实现完全一致
不含任何 Flask 依赖，所有模块都可以安全 import 它。"""

import os
import sys


# ---------------------------------------------------------------------------
# 程序名称与版本（排错与发布用；版本格式 主.次.修订）
# ---------------------------------------------------------------------------
APP_NAME = "Shelfmark"
APP_VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# 运行模式与路径（打包版 / 源码版 双基地）
# ---------------------------------------------------------------------------
# PyInstaller 打包（--onefile）后：
#   - sys.frozen = True
#   - RUNTIME_DIR = exe 所在目录 —— 用户可写数据区。书库 data/、封面 covers/、
#     日志、发布配置都放这里（换电脑 = 拷贝 exe + data + covers 即迁移）
#   - RES_DIR = exe 内部解压区 (_MEIPASS) —— 只读内置资源（模板 / 静态基础文件）
# 源码运行（python app.py / start.bat）时两者相同，行为完全不变。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    RUNTIME_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RES_DIR = getattr(sys, "_MEIPASS", RUNTIME_DIR)
else:
    RUNTIME_DIR = RES_DIR = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = RES_DIR          # 内置资源根（打包版=exe 内部；源码版=项目目录）
DATA_DIR = os.path.join(RUNTIME_DIR, "data")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 在线只读浏览站（GitHub Pages）发布状态文件与默认站点目录。
# 站点目录解析见 get_site_dir()：环境变量 SITE_DIR > data/config.json 的 site_dir > 默认约定。
# 默认约定 = 与程序目录【同级】的 library-web 文件夹 —— 不写死任何个人路径；
# 若站点仓库不在该位置，在 data/config.json 写入 {"site_dir": "你的路径"} 即可，无需改代码。
DEFAULT_SITE_DIR = os.path.join(
    os.path.dirname(os.path.normpath(RUNTIME_DIR)), "library-web")
PUBLISH_STATE_FILE = os.path.join(DATA_DIR, "publish_state.json")

# 批量导入支持的电子书格式（按扩展名筛选）
ALLOWED_FORMATS = {".pdf", ".epub", ".mobi"}

# 表单下拉选项
STATUS_OPTIONS = ["未读", "在读", "已读", "搁置"]
RATING_OPTIONS = [0, 1, 2, 3, 4, 5]
FORMAT_OPTIONS = ["pdf", "epub", "mobi", "其他"]

# 封面图片上传：封面图目录（运行时新增都写这里，打包版=exe 旁 covers/，源码版=static/covers/）
if IS_FROZEN:
    COVER_UPLOAD_DIR = os.path.join(RUNTIME_DIR, "covers")
else:
    COVER_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "covers")
ALLOWED_COVER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                     ".svg", ".bmp"}                             # 允许的图片格式
MAX_COVER_SIZE = 5 * 1024 * 1024                                 # 单张封面最大 5MB

# 分页 / 封面墙
PAGE_SIZE_LIST = 108     # 表格视图每页本数
PAGE_SIZE_CARDS = 108    # 封面墙每页本数
SHELF_COUNT = 9          # 「最近添加 / 随机发现」各展示本数
