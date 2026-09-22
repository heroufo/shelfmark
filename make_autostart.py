# -*- coding: utf-8 -*-
"""
生成「开机自启」脚本（VBS，无窗口后台运行）并安装到 Windows 启动文件夹。
用法: python make_autostart.py
设计要点:
- VBS 文件内容为【纯 ASCII】：中文路径用 ChrW() 按 Unicode 码点拼接，
  彻底规避 编码/乱码 问题（无论用记事本、VS Code 还是 WSH 解析都不乱码）。
- 会生成两份: ① 程序目录内的可迁移副本 ② 启动文件夹（%APPDATA%\\...\\Startup）内生效副本
- 取消自启: 删除启动文件夹中的 library-autostart.vbs 即可
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE_DIR, "app.py")


def find_pythonw():
    """
    定位「无控制台窗口」的 pythonw.exe，不写死任何个人路径：
    1) 当前解释器同目录下的 pythonw.exe（虚拟环境场景）
    2) 当前解释器本身即 pythonw 时直接使用
    3) 退回 PATH 中的 pythonw
    """
    exe = sys.executable or ""
    if exe:
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(cand):
            return cand
        if os.path.basename(exe).lower() == "pythonw.exe":
            return exe
    return "pythonw.exe"


PYW = find_pythonw()


def to_chrw(path):
    """把路径中每个非 ASCII 字符转成 ChrW(&HXXXX)，返回（前缀ASCII串, ChrW表达式）。"""
    prefix = ""
    parts = []
    for ch in path:
        if ord(ch) < 128:
            prefix += ch
        else:
            parts.append("ChrW(&H%04X)" % ord(ch))
    return prefix, " & ".join(parts)


def main():
    app_prefix, app_chrw = to_chrw(APP)
    dir_prefix, dir_chrw = to_chrw(BASE_DIR)
    # 纯 ASCII 的 VBS：中文路径由 ChrW() 拼接，文件本身不含任何非 ASCII 字节
    content = (
        "' Shelfmark - auto start (no console window, no browser auto-open)\n"
        "' To disable: delete this file from the Startup folder (Win+R -> shell:startup)\n"
        'DirLib = "{0}" & {1}\n'
        'Set ws = CreateObject("Wscript.Shell")\n'
        'ws.CurrentDirectory = DirLib\n'
        'ws.Run """"{2}"" """ & DirLib & "\\{3}"", 0, False\n'
    ).format(dir_prefix, dir_chrw, PYW, os.path.basename(APP))

    startup_dir = os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\Startup")
    targets = [
        os.path.join(BASE_DIR, "启动Shelfmark.vbs"),
        os.path.join(startup_dir, "library-autostart.vbs"),
    ]
    for p in targets:
        # 内容为纯 ASCII，用 ascii 编码写入最安全
        with open(p, "w", encoding="ascii", newline="\r\n") as f:
            f.write(content)
        print("written:", p)
    # 读回验证：应全部为 ASCII
    for p in targets:
        with open(p, encoding="ascii") as f:
            text = f.read()
        print("---", p, "---")
        print(text)
        print("is pure ASCII:", text.isascii())


if __name__ == "__main__":
    main()
