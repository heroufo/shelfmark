# -*- mode: python ; coding: utf-8 -*-
# =====================================================================
# Shelfmark — PyInstaller 单文件打包配置（onefile, 无控制台）
# 用法（在项目根目录）:
#   pyinstaller --noconfirm --clean --distpath dist_exe shelfmark.spec
# 产物: dist_exe/Shelfmark.exe  （内置 Python 运行时, 目标机免装 Python）
# =====================================================================
import os

from PyInstaller.utils.hooks import collect_submodules

PROJECT = os.path.abspath(SPECPATH)   # spec 所在目录 = 项目根

# 内置只读资源（模板 + 静态基础文件）。
# 注意：static/covers（封面）刻意不打包 —— 打包版封面外置于 exe 旁 covers/，
#       见 shelfmark/paths.py 的 RUNTIME_DIR 与 app.py 的 covers 转发路由。
datas = [
    (os.path.join(PROJECT, "templates"), "templates"),
    (os.path.join(PROJECT, "static", "css"), "static/css"),
    (os.path.join(PROJECT, "static", "js"), "static/js"),
    (os.path.join(PROJECT, "static", "images"), "static/images"),
]

a = Analysis(
    [os.path.join(PROJECT, "app.py")],
    pathex=[PROJECT],
    binaries=[],
    datas=datas,
    # 显式收集内部包（含 views 子包）：即使将来出现动态/条件导入也不会漏
    hiddenimports=collect_submodules("shelfmark") + ["export_data"],
    hookspath=[],
    runtime_hooks=[],
    # 打包版不再依赖 tkinter（文件对话框已改用 Windows 原生 API），排除以减体积
    excludes=["tkinter", "test", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Shelfmark",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # 无控制台窗口（双击静默后台运行，日志写 data/app.log）
    icon=os.path.join(PROJECT, "build_exe", "icon.ico"),
    disable_windowed_traceback=False,
)
