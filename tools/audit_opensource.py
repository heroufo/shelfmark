# -*- coding: utf-8 -*-
"""
开源就绪度体检 —— 只读扫描，不修改任何文件。

检查四类问题：
  1) 结构和开源标配文件是否齐备
  2) 隐私 / 敏感信息（本机绝对路径、口令、邮箱、个人数据）
  3) 法律风险（第三方注册商标词、疑似侵权素材）
  4) .gitignore 是否覆盖了隐私与版权素材目录

用法：
    python tools/audit_opensource.py          # 输出报告，有 P0 问题时退出码 1
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {"static", "dist_exe", "backup_pre_exe", "build", "build_exe",
             ".git", "__pycache__", ".workbuddy", "data", "node_modules",
             ".venv", "venv"}
SCAN_EXT = {".py", ".html", ".htm", ".md", ".txt", ".bat", ".vbs", ".spec",
            ".json", ".cfg", ".toml", ".yml", ".yaml", ".js", ".css", ".svg"}

# P0 = 阻断发布；P1 = 需要人工确认
PATTERNS = [
    ("P0", "本机绝对路径", r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z]+"),
    ("P0", "个人同步盘路径", r"同步盘"),
    ("P0", "疑似口令 / 密钥", r"198419419|password\s*=\s*['\"][^'\"]+"
                            r"|api[_-]?key\s*=\s*['\"][^'\"]+"),
    ("P0", "第三方注册商标词", r"Hogwarts|Harry\s?Potter|霍格沃茨"),
    ("P0", "开发机虚拟环境路径", r"\.workbuddy[\\/]+binaries"),
    ("P0", "WorkBuddy 平台内部路径", r"WorkBuddy"),
    ("P1", "默认站点目录名", r"library-web"),
    ("P1", "邮箱地址", r"[\w.+-]+@[\w-]+\.[\w.]+"),
]

REQUIRED = ["LICENSE", ".gitignore", "README.md", "CONTRIBUTING.md",
            ".editorconfig", "requirements.txt", "requirements-dev.txt",
            "THIRD_PARTY_NOTICES.md", "tests", "tools"]

# .gitignore 必须覆盖的目录（隐私 / 版权 / 构建产物）
MUST_IGNORE = ["data/", "static/covers/", "dist_exe/", "build/", "backup"]


def scan_text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SCAN_EXT:
                yield os.path.join(dirpath, fn)


def main():
    print("=" * 72)
    print("1) 开源标配文件")
    print("=" * 72)
    missing = []
    for f in REQUIRED:
        ok = os.path.exists(os.path.join(ROOT, f))
        if not ok:
            missing.append(f)
        print("   %-24s %s" % (f, "OK" if ok else "缺失"))

    print()
    print("=" * 72)
    print("2) .gitignore 覆盖范围")
    print("=" * 72)
    gi_path = os.path.join(ROOT, ".gitignore")
    gi = open(gi_path, encoding="utf-8").read() if os.path.isfile(gi_path) else ""
    for d in MUST_IGNORE:
        ok = d in gi
        print("   %-22s %s" % (d, "已忽略" if ok else "!! 未忽略"))

    print()
    print("=" * 72)
    print("3) 隐私 / 法律风险扫描")
    print("=" * 72)
    hits = {k: [] for _, k, _ in PATTERNS}
    level = {k: lv for lv, k, _ in PATTERNS}
    skip_self = {"tools/audit_opensource.py", "tools/rename_brand.py"}
    for fp in scan_text_files():
        rel = os.path.relpath(fp, ROOT)
        if rel.replace("\\", "/") in skip_self:
            continue      # 规则表 / 改名映射表本身含敏感与品牌词，跳过
        try:
            text = open(fp, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for _, name, pat in PATTERNS:
                if re.search(pat, line):
                    hits[name].append("%s:%d: %s" % (rel, i, line.strip()[:88]))

    p0_count = 0
    for _, name, _ in PATTERNS:
        items = hits[name]
        if items and level[name] == "P0":
            p0_count += len(items)
        print("   [%s] %-18s 命中 %d 处" % (level[name], name, len(items)))
        for it in items[:5]:
            print("          ", it)
        if len(items) > 5:
            print("           ... 另有 %d 处" % (len(items) - 5))

    print()
    print("=" * 72)
    print("4) 结论")
    print("=" * 72)
    if missing:
        print("   缺失开源标配文件：%s" % "、".join(missing))
    if p0_count:
        print("   !! 存在 %d 处 P0 风险，发布前必须清理。" % p0_count)
    elif not missing:
        print("   P0 检查全部通过，可以发布。")
    else:
        print("   无 P0 风险，建议补齐缺失文件。")
    return 1 if p0_count else 0


if __name__ == "__main__":
    sys.exit(main())
