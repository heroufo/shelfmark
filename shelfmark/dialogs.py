# -*- coding: utf-8 -*-
"""系统原生对话框与「用默认程序打开文件」。

两种实现路径并存，按运行模式自动选择：
  - 源码版：子进程调用带 tkinter 的系统 pythonw 执行 file_dialog_helper.py
  - 打包版：ctypes 直接调用 Windows 原生 API（GetOpenFileNameW /
    SHBrowseForFolderW），目标机器无需安装 Python
取消失败一律返回 None，绝不抛异常给上层。"""

from datetime import datetime
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid

from shelfmark.paths import BASE_DIR, DATA_DIR, IS_FROZEN


_DIALOG_PYTHON_CACHE = None  # 缓存带 tkinter 的 pythonw 路径（仅命中时缓存，避免每次点击重新探测）


def _find_dialog_python():
    """
    找到带 tkinter 的 pythonw / python 解释器（用于弹出系统原生文件对话框）。
    结果会缓存，避免每次点击「浏览…」都重新探测所有 Python 候选（这是卡顿主因）。
    """
    global _DIALOG_PYTHON_CACHE
    if _DIALOG_PYTHON_CACHE is not None:
        return _DIALOG_PYTHON_CACHE
    candidates = [
        # 当前解释器（venv 场景最常见）
        os.path.join(os.path.dirname(sys.executable or ""), "pythonw.exe"),
        sys.executable,
        # 微软商店版 / 官方安装版的常见位置（用环境变量，不写死用户名）
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python313\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python312\pythonw.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Python311\pythonw.exe"),
        r"C:\Python313\pythonw.exe",
        r"C:\Python312\pythonw.exe",
        r"C:\Python311\pythonw.exe",
        # PATH 中的兜底（探测到不带 tkinter 会自动跳过）
        shutil.which("pythonw"),
        shutil.which("python"),
    ]
    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "import tkinter"],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                _DIALOG_PYTHON_CACHE = cand
                return cand
        except Exception:
            continue
    return None


def open_file_with_default_app(path):
    """跨平台调用系统默认程序打开文件（Windows: startfile）。"""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def pick_file_dialog():
    """
    弹出系统原生「选择文件」对话框，返回用户选中的本地文件路径。
    - 打包版：ctypes 调 Windows 原生 API（GetOpenFileNameW），零 Python 依赖
    - 源码版：以子进程方式调用带 tkinter 的系统 pythonw.exe
      执行 file_dialog_helper.py（与历史行为一致）
    - 用户取消或任何一步失败均返回 None，不抛异常
    """
    return _pick_dialog("file")


def pick_folder_dialog():
    """
    弹出系统原生「选择目录」对话框（批量导入用），返回选中的文件夹路径。
    与 pick_file_dialog 同一机制，仅对话框类型不同。
    """
    return _pick_dialog("folder")


def _pick_dialog(mode="file"):
    """
    pick_file_dialog / pick_folder_dialog 的公共实现：
    - 打包版：直接走 _native_dialog（Windows 原生 API）
    - 源码版：子进程调用 file_dialog_helper.py（mode: file|folder）并读取输出文件
    """
    if IS_FROZEN:
        try:
            return _native_dialog(mode)
        except Exception:
            return None
    helper = os.path.join(BASE_DIR, "file_dialog_helper.py")
    pythonw = _find_dialog_python()
    if not os.path.isfile(helper) or not pythonw:
        return None
    tmp_file = os.path.join(tempfile.gettempdir(),
                            "ebook_pick_" + uuid.uuid4().hex + ".txt")
    try:
        subprocess.run([pythonw, helper, tmp_file, mode], timeout=300)
        if os.path.exists(tmp_file):
            with open(tmp_file, "r", encoding="utf-8") as f:
                path = f.read().strip()
            return path or None
    except Exception:
        return None
    finally:
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception:
            pass
    return None


def _native_log(msg):
    """
    把原生对话框相关诊断信息追加写入 data/app.log。
    打包版无控制台窗口，出错只能靠日志排查，故任何异常都留痕。
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "app.log"), "a",
                  encoding="utf-8") as f:
            f.write("[%s] %s\n"
                    % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _native_dialog(mode="file"):
    """
    打包版专用：Windows 原生文件/目录选择对话框（纯 ctypes，无 tkinter）。
    可在任意线程调用（模态对话框自带消息循环）。
    mode: file → GetOpenFileNameW 选择电子书文件；folder → SHBrowseForFolderW 选择目录。
    取消或失败返回 None（失败原因写 data/app.log）。
    """
    import ctypes
    from ctypes import wintypes

    try:
        if mode == "folder":
            return _native_pick_folder(ctypes, wintypes)
        return _native_pick_file(ctypes, wintypes)
    except Exception as e:
        _native_log("原生对话框异常(mode=%s): %r" % (mode, e))
        return None


def _native_pick_folder(ctypes, wintypes):
    """SHBrowseForFolderW 目录选择框。返回目录路径或 None。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    # 必须显式声明 restype：SHBrowseForFolderW 返回 PIDL 指针，
    # 默认 c_long 会把 64 位地址截断，导致后续转换访问违例。
    browse = shell32.SHBrowseForFolderW
    browse.argtypes = [ctypes.c_void_p]
    browse.restype = ctypes.c_void_p
    get_path = shell32.SHGetPathFromIDListW
    get_path.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    get_path.restype = wintypes.BOOL

    ole32.CoInitialize(None)
    try:
        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                # 用 c_void_p 承载缓冲区地址：若声明 LPWSTR，读取字段会返回
                # Python str（无 .value），且无法保证缓冲区生命周期。
                ("pszDisplayName", ctypes.c_void_p),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            ]

        display_buf = ctypes.create_unicode_buffer(260)
        path_buf = ctypes.create_unicode_buffer(4096)
        bi = BROWSEINFOW()
        bi.hwndOwner = None
        bi.pszDisplayName = ctypes.addressof(display_buf)
        bi.lpszTitle = "选择电子书目录（批量导入）"
        # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE（新版树形对话框，可输入路径）
        bi.ulFlags = 0x00000001 | 0x00000040
        pidl = browse(ctypes.addressof(bi))
        if pidl:
            if get_path(pidl, ctypes.addressof(path_buf)) and path_buf.value:
                return path_buf.value
            _native_log("目录选择：PIDL 转路径失败 pidl=%s" % pidl)
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass
    return None


def _native_pick_file(ctypes, wintypes):
    """GetOpenFileNameW 文件选择框（电子书格式过滤）。返回文件路径或 None。"""
    comdlg32 = ctypes.windll.comdlg32
    ole32 = ctypes.windll.ole32

    get_open = comdlg32.GetOpenFileNameW
    get_open.argtypes = [ctypes.c_void_p]
    get_open.restype = wintypes.BOOL
    ext_err = comdlg32.CommDlgExtendedError
    ext_err.argtypes = []
    ext_err.restype = wintypes.DWORD

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", ctypes.c_void_p),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            # lpstrFile 必须是可写缓冲区；用 c_void_p + addressof 赋值，
            # 结果直接从 path_buf 读取。若声明为 LPWSTR，读取字段得到的是
            # Python str（再取 .value 会 AttributeError）。
            ("lpstrFile", ctypes.c_void_p),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", ctypes.c_void_p),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
        ]

    ole32.CoInitialize(None)
    try:
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = None
        ofn.lpstrFilter = ("电子书文件\0*.pdf;*.epub;*.mobi\0"
                           "所有文件\0*.*\0\0")
        ofn.nFilterIndex = 1
        ofn.lpstrTitle = "选择电子书文件"
        path_buf = ctypes.create_unicode_buffer(32768)
        ofn.lpstrFile = ctypes.addressof(path_buf)
        ofn.nMaxFile = 32768
        ofn.lpstrInitialDir = None
        # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY
        # | OFN_EXPLORER | OFN_ENABLESIZING
        ofn.flags = (0x00001000 | 0x00000800 | 0x00000004
                     | 0x00080000 | 0x00800000)
        if get_open(ctypes.addressof(ofn)):
            return path_buf.value or None
        # 返回 0：用户取消（错误码 0）或结构体/参数错误（非 0 错误码）
        _native_log("文件选择未返回路径 CommDlgExtendedError=%d" % ext_err())
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass
    return None
