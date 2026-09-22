# -*- coding: utf-8 -*-
"""把项目文件夹改名（默认 图书管理 → shelfmark），并留下旧名目录联接。

用法
----
    # 推荐：先彻底关闭 WorkBuddy / 编辑器 / 同步客户端，再双击项目根目录的
    #       rename-folder.cmd（它会先把工作目录挪出项目文件夹）
    python tools/rename_project_folder.py
    python tools/rename_project_folder.py --to shelfmark --dry-run
    python tools/rename_project_folder.py --no-junction      # 不留旧名联接

为什么需要"先关闭程序"再执行
--------------------------
Windows 不允许改名一个"正被某进程当作工作目录或打开着"的文件夹，报错为
`另一个进程正在使用此文件`。当 WorkBuddy 正打开着本项目时，这个会话本身
就持有该文件夹，因此改名必须在程序关闭后进行。

脚本做了什么
------------
1. 把项目文件夹改名为目标名（重试若干次，失败时给出明确提示）
2. 在旧位置建立一个**目录联接（junction）**指向新目录 —— 这样已经存在的
   桌面快捷方式、开机自启 VBS、以及仍指向旧路径的任何引用都继续可用
3. 尽力更新两处引用到新路径：开机自启 VBS、桌面快捷方式（指向 exe）
4. 任何一步失败都会自动回滚，不会留下"半改名"状态

若不需要保留旧名联接（例如你确定所有引用都已更新），用 --no-junction，
这样旧文件夹名会彻底消失。
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(PROJECT)
OLD_NAME = os.path.basename(PROJECT)
DEFAULT_NEW_NAME = "shelfmark"

STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""),
                           "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
AUTOSTART_VBS = os.path.join(STARTUP_DIR, "library-autostart.vbs")
DESKTOP = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def say(msg):
    print(msg, flush=True)


def vbs_concat(text):
    """把字符串转成 VBScript 表达式：ASCII 连续段用引号字面量，非 ASCII 用 ChrW 拼接。

    这样生成的 .vbs 文件本身永远是纯 ASCII，不依赖任何代码页，中文路径也不会乱码。
    例：C:\\...\\WorkBuddy\\图书管理  ->  "C:\\...\\WorkBuddy\\" & ChrW(&H56FE) & …
    """
    parts = []
    buf = []
    for ch in text:
        if 32 <= ord(ch) < 127 and ch != '"':
            buf.append(ch)
        else:
            if buf:
                parts.append('"%s"' % "".join(buf))
                buf = []
            parts.append("ChrW(&H%X)" % ord(ch))
    if buf:
        parts.append('"%s"' % "".join(buf))
    return " & ".join(parts) if parts else '""'


def find_pythonw():
    """定位 pythonw.exe（优先当前解释器同目录，其次同 env 的 Scripts/，最后 PATH）。"""
    exe_dir = os.path.dirname(sys.executable)
    for cand in (os.path.join(exe_dir, "pythonw.exe"),
                 os.path.normpath(os.path.join(exe_dir, "..", "Scripts", "pythonw.exe"))):
        if os.path.isfile(cand):
            return cand
    return "pythonw"


def write_autostart_vbs(new_dir, pythonw):
    """重写开机自启 VBS，使其指向新目录。"""
    if not os.path.isdir(STARTUP_DIR):
        return "跳过（未找到启动文件夹）"
    body = (
        "' Shelfmark - auto start (no console window, no browser auto-open)\n"
        "' To disable: delete this file from the Startup folder (Win+R -> shell:startup)\n"
        "DirLib = %s\n"
        "Set ws = CreateObject(\"Wscript.Shell\")\n"
        "ws.CurrentDirectory = DirLib\n"
        "ws.Run \"\"\"%s\"\" \"\"\" & DirLib & \"\\app.py\"\"\", 0, False\n"
        % (vbs_concat(new_dir), pythonw)
    )
    try:
        with open(AUTOSTART_VBS, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(body)
        return "已更新 %s" % AUTOSTART_VBS
    except OSError as exc:
        return "更新失败：%s" % exc


def fix_desktop_shortcut(new_dir):
    """把桌面上的图书馆快捷方式改名并重指向 dist_exe\\Shelfmark.exe。"""
    if not os.path.isdir(DESKTOP):
        return "跳过（未找到桌面目录）"

    wanted = os.path.join(DESKTOP, "Shelfmark.lnk")
    found = []
    for name in os.listdir(DESKTOP):
        if not name.lower().endswith(".lnk"):
            continue
        if "图书馆" in name or "Shelfmark" in name:
            found.append(os.path.join(DESKTOP, name))
    if not found:
        return "跳过（桌面没有相关快捷方式）"

    for src in found:
        if os.path.normcase(src) == os.path.normcase(wanted):
            continue
        try:
            os.replace(src, wanted)
        except OSError:
            pass

    exe = os.path.join(new_dir, "dist_exe", "Shelfmark.exe")
    if not os.path.isfile(exe):
        return "跳过（尚未打包 dist_exe\\Shelfmark.exe）"

    vbs = os.path.join(tempfile.gettempdir(), "shelfmark_mk_lnk.vbs")
    lines = [
        'Set s = CreateObject("WScript.Shell")',
        'Set t = s.CreateShortcut("%s")' % wanted,
        't.TargetPath = "%s"' % exe,
        't.WorkingDirectory = "%s"' % os.path.dirname(exe),
        't.Description = "Shelfmark - private library"',
        't.Save',
    ]
    try:
        # cscript 支持带 BOM 的 UTF-16 脚本，用它写可安全容纳中文路径
        with open(vbs, "w", encoding="utf-16", newline="\r\n") as fh:
            fh.write("\r\n".join(lines) + "\r\n")
    except OSError as exc:
        return "更新失败：%s" % exc

    rc, out = run_tool(["cscript", "//nologo", vbs])
    try:
        os.remove(vbs)
    except OSError:
        pass

    if rc != 0:
        return "更新失败：%s" % (out or "exit %s" % rc)
    return "已把桌面快捷方式指向 %s" % exe


def run_tool(cmd):
    """运行外部命令，返回 (returncode, 合并后的输出文本)。

    注意：不能给 subprocess 传 text=True —— cmd.exe / cscript 输出的是本机 ANSI
    代码页（中文 Windows 为 GBK），按 UTF-8 解码会抛 UnicodeDecodeError，进而让
    stdout 变成 None。这里按字节收，再逐个编码尝试解码。
    """
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except OSError as exc:
        return 1, "无法启动 %s：%s" % (cmd[0], exc)

    def decode(raw):
        if not raw:
            return ""
        for enc in ("mbcs", "utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return repr(raw)

    return proc.returncode, (decode(proc.stdout) + decode(proc.stderr)).strip()


def make_junction(old, new):
    """建立目录联接（junction，不需要管理员权限）。"""
    return run_tool(["cmd", "/c", "mklink", "/J", old, new])


def main():
    ap = argparse.ArgumentParser(description="改名项目文件夹并留下旧名目录联接")
    ap.add_argument("--to", default=DEFAULT_NEW_NAME, help="新的文件夹名")
    ap.add_argument("--no-junction", action="store_true", help="不保留旧名联接")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不做改动")
    ap.add_argument("--retries", type=int, default=4, help="改名重试次数")
    args = ap.parse_args()

    old = PROJECT
    new = os.path.join(PARENT, args.to)

    say("=" * 64)
    say("项目文件夹改名")
    say("  当前位置 : %s" % old)
    say("  目标位置 : %s" % new)
    say("  旧名联接 : %s" % ("不保留" if args.no_junction else "保留（兼容旧快捷方式）"))
    say("=" * 64)

    if os.path.normcase(os.path.basename(old)) == os.path.normcase(args.to):
        say("[跳过] 文件夹已经叫 %s 了。" % args.to)
        return 0

    if args.dry_run:
        say("[dry-run] 未做任何改动。")
        return 0

    if os.path.exists(new):
        say("[失败] 目标已存在：%s" % new)
        return 1

    # ---- 1. 改名（带重试） ----
    renamed = False
    for i in range(1, args.retries + 1):
        try:
            os.rename(old, new)
            renamed = True
            say("[1/4] 改名成功（第 %d 次尝试）" % i)
            break
        except OSError as exc:
            say("[1/4] 第 %d 次失败：%s" % (i, exc.strerror or exc))
            if i < args.retries:
                say("      —— 文件夹被占用，3 秒后重试…")
                time.sleep(3)
    if not renamed:
        say("")
        say("[失败] 文件夹正被占用，无法改名。")
        say("       请彻底退出 WorkBuddy，并关掉资源管理器里打开本项目的窗口、")
        say("       编辑器、以及同步盘客户端，然后重新双击 rename-folder.cmd。")
        return 1

    def rollback(reason):
        """把文件夹改回原名（先摘掉联接，避免连带处理目标目录）。"""
        say("      —— %s，自动回滚" % reason)
        try:
            if os.path.isdir(old):
                os.rmdir(old)          # rmdir 只删联接本身，不动目标目录
        except OSError:
            pass
        try:
            os.rename(new, old)
            say("      已回滚到原名，项目未受影响。")
            return True
        except OSError as exc:
            say("      回滚失败：%s" % exc)
            say("      请手动把 %s 改回 %s" % (new, old))
            return False

    # ---- 2~4 步：建联接 → 更新引用 → 校验；任何异常都回滚 ----
    try:
        if args.no_junction:
            say("[2/4] 按要求不建立旧名联接")
        else:
            rc, out = make_junction(old, new)
            if rc != 0 or not os.path.isdir(old):
                say("[2/4] 建立旧名联接失败：%s" % out)
                rollback("联接未建立")
                return 1
            say("[2/4] 已建立旧名联接：%s → %s" % (old, new))

        say("[3a/4] 开机自启：" + write_autostart_vbs(new, find_pythonw()))
        say("[3b/4] 桌面快捷方式：" + fix_desktop_shortcut(new))

        say("[4/4] 校验：")
        checks = [("新目录可访问（见到 shelfmark.spec）",
                   os.path.isfile(os.path.join(new, "shelfmark.spec")))]
        if args.no_junction:
            checks.append(("旧名已彻底移除", not os.path.exists(old)))
        else:
            checks.append(("旧名联接可用（旧路径仍能访问项目）",
                           os.path.isdir(old) and os.path.isfile(
                               os.path.join(old, "shelfmark.spec"))))
        ok = True
        for label, passed in checks:
            say("      %s %s" % ("OK  " if passed else "FAIL", label))
            ok = ok and passed
    except Exception as exc:  # noqa: BLE001  兜底：绝不留半改名状态
        say("[异常] %r" % (exc,))
        rollback("出现未预期异常")
        return 3

    say("")
    if ok:
        say("完成。项目现在位于：%s" % new)
        if not args.no_junction:
            say("提示：旧路径 %s 仍可用（目录联接）。" % old)
            say("      · 要在 WorkBuddy 里继续打开本项目，请把工作区重新添加到新路径；")
            say("      · 确认所有引用都改好后，可以删掉旧名联接。")
        return 0
    say("校验未通过，请把上面的输出发回给我。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
