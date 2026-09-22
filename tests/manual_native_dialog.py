# -*- coding: utf-8 -*-
"""
自动化验证 Windows 原生文件 / 目录选择对话框（产品代码 _native_dialog）。

原理：主线程调用产品函数弹出模态对话框；辅助线程轮询找到该对话框，
自动填入测试路径并点击「确定」，从而无需人工点击即可验证完整链路。

用法：python _test_native_dialog.py
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app as A  # noqa: E402

user32 = ctypes.windll.user32
WM_COMMAND = 0x0111
WM_SETTEXT = 0x000C
IDOK = 1
CTL_FILENAME = 0x047C          # comdlg32 文件名组合框（cmb13）
BFFM_SETSELECTION = 0x0400 + 102  # 目录对话框设置初始路径

TEST_DIR = os.path.join(HERE, "_dlgtest")
TEST_FILE = os.path.join(TEST_DIR, "测试书籍.pdf")
FOLDER_TO_PICK = HERE

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                     wintypes.LPARAM)


def find_dialog(title_kw):
    """title_kw 为 None 时匹配任意对话框（并记录其标题，便于诊断）。"""
    found = []
    titles = []

    def cb(h, _l):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if cls.value == "#32770":
            titles.append(buf.value)
            if title_kw is None or title_kw in buf.value:
                found.append(h)
                return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    find_dialog.last_titles = titles
    return found


def find_edit(hwnd):
    """在对话框子窗口中找可输入的编辑框。"""
    h = user32.GetDlgItem(hwnd, CTL_FILENAME)
    if h:
        return h
    found = []

    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if cls.value in ("Edit", "ComboBoxEx32", "ComboBox"):
            found.append(h)
            return False
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(cb), 0)
    return found[0] if found else None


def driver(title_kw, path, result, is_folder=False):
    for _ in range(120):          # 最多等 30 秒
        time.sleep(0.25)
        hs = find_dialog(title_kw)
        if not hs:
            continue
        hwnd = hs[0]
        result["found"] = True
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if is_folder:
            r = user32.SendMessageW(hwnd, BFFM_SETSELECTION, 1, path)
            result["setsel"] = r
        else:
            ed = find_edit(hwnd)
            result["edit"] = bool(ed)
            if ed:
                user32.SendMessageW(ed, WM_SETTEXT, 0, path)
        time.sleep(0.3)
        user32.SendMessageW(hwnd, WM_COMMAND, IDOK, 0)
        result["clicked"] = True
        return
    result["timeout"] = True


def run_case(mode, title_kw, path):
    res = {}
    t = threading.Thread(target=driver, args=(title_kw, path, res,
                                              mode == "folder"),
                         daemon=True)
    t.start()
    try:
        out = A._native_dialog(mode)
    except Exception as e:
        out = "EXC: %r" % (e,)
    t.join(3)
    print("[%s] 返回 = %r" % (mode, out))
    print("[%s] 驱动状态 = %s" % (mode, res))
    print("[%s] 枚举到的对话框标题 = %s"
          % (mode, getattr(find_dialog, "last_titles", None)))
    ok = isinstance(out, str) and out and not out.startswith("EXC")
    print("[%s] => %s" % (mode, "PASS" if ok else "FAIL"))
    return ok


def main():
    os.makedirs(TEST_DIR, exist_ok=True)
    with open(TEST_FILE, "wb") as f:
        f.write(b"%PDF-1.4 fake test file\n")
    print("测试文件:", TEST_FILE)
    r1 = run_case("file", "选择电子书文件", TEST_FILE)
    time.sleep(1)
    # 目录对话框用 None 匹配任意 #32770（不同 Win 版本标题栏文本略有差异）
    r2 = run_case("folder", None, FOLDER_TO_PICK)
    print("=" * 40)
    print("RESULT file=%s folder=%s" % ("PASS" if r1 else "FAIL",
                                        "PASS" if r2 else "FAIL"))


if __name__ == "__main__":
    main()
