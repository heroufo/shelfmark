# -*- coding: utf-8 -*-
"""
exe 端到端验证「浏览…」按钮链路：
  启动打包 exe → 自动驱动原生文件对话框选文件并点确定 → 请求 /api/browse_file
  → 校验返回的 JSON 是否 ok=true 且路径正确。

用法：python _test_exe_browse.py
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
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist_exe")
EXE = os.path.join(DIST, "Shelfmark.exe")
PORT = 5023
BASE = "http://127.0.0.1:%d" % PORT
TEST_DIR = os.path.join(ROOT, "_dlgtest")
TEST_FILE = os.path.join(TEST_DIR, "测试书籍.pdf")

user32 = ctypes.windll.user32
WM_COMMAND = 0x0111
WM_SETTEXT = 0x000C
IDOK = 1
CTL_FILENAME = 0x047C
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                     wintypes.LPARAM)

# ---- 全局键盘输入（模拟真人敲字，跨进程可靠，不依赖 WM_SETTEXT 封送） ----
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 24)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]


def _send(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(vk, scan, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def type_text(text):
    for ch in text:
        _send(scan=ord(ch), flags=KEYEVENTF_UNICODE)
        _send(scan=ord(ch), flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.01)


def press_enter():
    _send(vk=VK_RETURN)
    _send(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)


def find_dialog(title_kw):
    found = []

    def cb(h, _l):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if cls.value == "#32770" and title_kw in buf.value:
            found.append(h)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def press_ctrl_a():
    _send(vk=0x11)
    _send(vk=0x41)
    _send(vk=0x41, flags=KEYEVENTF_KEYUP)
    _send(vk=0x11, flags=KEYEVENTF_KEYUP)


def find_inner_edit(hwnd):
    """0x047C 是 ComboBoxEx32，真正的文件名输入框是它内部的 Edit 子窗口。"""
    found = []

    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        if cls.value == "Edit":
            found.append(h)
            return False
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def force_foreground(hwnd):
    """跨进程强制把对话框拉到前台并把焦点放到文件名输入框。"""
    k32 = ctypes.windll.kernel32
    cur_tid = k32.GetCurrentThreadId()
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached = False
    if tgt_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, tgt_tid, True))
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    ed = user32.GetDlgItem(hwnd, CTL_FILENAME)
    if ed:
        user32.SetFocus(ed)
    if attached:
        user32.AttachThreadInput(cur_tid, tgt_tid, False)
    return ed


def driver(title_kw, path, result):
    """等对话框出现 → 强制激活 → 全选清空 → 敲入完整路径 → 回读校验 → 回车。"""
    for _ in range(160):          # 最多等 40 秒
        time.sleep(0.25)
        hs = find_dialog(title_kw)
        if not hs:
            continue
        hwnd = hs[0]
        result["found"] = True
        force_foreground(hwnd)
        time.sleep(0.6)
        press_ctrl_a()
        time.sleep(0.2)
        type_text(path)
        time.sleep(0.4)
        result["typed"] = True
        inner = find_inner_edit(hwnd)
        buf = ctypes.create_unicode_buffer(1024)
        if inner:
            user32.GetWindowTextW(inner, buf, 1024)
        result["edit_text"] = buf.value
        press_enter()
        result["clicked"] = True
        return
    result["timeout"] = True


def wait_ready(timeout=90):
    for _ in range(timeout * 2):
        try:
            with urllib.request.urlopen(BASE + "/", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    if not os.path.isfile(EXE):
        print("FAIL: exe 不存在", EXE)
        return 1
    os.makedirs(TEST_DIR, exist_ok=True)
    with open(TEST_FILE, "wb") as f:
        f.write(b"%PDF-1.4 fake\n")

    env = dict(os.environ)
    env["PORT"] = str(PORT)
    env["NO_BROWSER"] = "1"
    env["PUBLISH_DRY_RUN"] = "1"
    proc = subprocess.Popen([EXE], cwd=DIST, env=env)
    print("exe 启动 PID =", proc.pid)
    try:
        if not wait_ready():
            print("FAIL: 服务未就绪")
            return 1
        print("服务就绪 OK")

        res = {}
        t = threading.Thread(target=driver,
                             args=("选择电子书文件", TEST_FILE, res),
                             daemon=True)
        t.start()
        time.sleep(0.5)
        with urllib.request.urlopen(BASE + "/api/browse_file",
                                    timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        t.join(3)
        print("驱动状态 =", res)
        print("API 返回  =", json.dumps(data, ensure_ascii=False))

        ok = (data.get("ok") is True
              and os.path.normcase(data.get("path", "")) ==
              os.path.normcase(TEST_FILE))
        # 打印 exe 日志中的版本与对话框诊断行，用于确认跑的是最新代码
        log = os.path.join(DIST, "data", "app.log")
        if os.path.isfile(log):
            keys = ("程序启动", "CommDlgExtendedError", "对话框异常",
                    "PIDL")
            lines = [ln for ln in open(log, encoding="utf-8",
                                       errors="ignore").read().splitlines()
                     if any(k in ln for k in keys)]
            print("exe 日志关键行:")
            for ln in lines[-6:]:
                print("   ", ln)
        print("=>", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.kill()
        try:
            proc.wait(5)
        except Exception:
            pass
        try:
            os.remove(TEST_FILE)
            os.rmdir(TEST_DIR)
        except Exception:
            pass
        print("exe 已停止，测试文件已清理")


if __name__ == "__main__":
    sys.exit(main())
