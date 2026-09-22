# -*- coding: utf-8 -*-
"""
品牌改名脚本 —— 批量替换项目内的品牌标识（可重复使用）。

用途
----
把历史品牌名（含第三方注册商标的旧名）替换为当前品牌名，覆盖源码、模板、
脚本、文档；并同步重命名与之绑定的文件。

设计
----
- 替换规则集中写在 REPLACEMENTS，改品牌只需改这里（或用 --to 覆盖）。
- 默认 dry-run 预览；加 --apply 才真正写盘（避免误改）。
- 自动跳过：版本控制目录、构建产物、用户数据、封面素材、二进制文件。

用法
----
    python tools/rename_brand.py                # 预览将要修改的文件
    python tools/rename_brand.py --apply        # 实际执行
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 替换规则：旧的品牌标识 -> 新的品牌标识（顺序敏感，长的写在前面）
# ---------------------------------------------------------------------------
REPLACEMENTS = [
    ("霍格沃茨图书馆", "Shelfmark"),
    ("Hogwarts Library", "Shelfmark"),
    ("hogwarts_library", "shelfmark"),
    ("hogwarts_logo", "shelfmark_logo"),
    ("Hogwarts", "Shelfmark"),
    ("hogwarts", "shelfmark"),
]

# 需要处理的文本扩展名
TEXT_EXT = {".py", ".html", ".htm", ".md", ".txt", ".bat", ".vbs", ".spec",
            ".json", ".yml", ".yaml", ".cfg", ".ini", ".editorconfig",
            ".gitignore", ".ps1", ".sh"}

# 不进入的目录（构建产物 / 用户数据 / 素材 / 版本控制）
SKIP_DIRS = {
    ".git", ".workbuddy", "__pycache__", "node_modules",
    "build", "dist", "dist_exe", "build_exe",
    "backup_pre_exe", "covers", "data", ".venv", "venv", ".idea", ".vscode",
}

# 文件改名映射（改名后路径）
RENAME_FILES = {
    "hogwarts_library.spec": "shelfmark.spec",
    "static/images/hogwarts_logo.png": "backup_pre_exe/_old_hogwarts_logo.png",
    "启动霍格沃茨图书馆.vbs": "backup_pre_exe/_old_autostart.vbs",
}


def iter_text_files():
    """遍历项目中需要做品牌替换的文本文件（跳过脚本自身，避免自替换）。"""
    me = os.path.abspath(__file__)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if os.path.abspath(path) == me:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT or fn in (".gitignore", ".editorconfig"):
                yield path


def preview():
    hits = []
    for path in iter_text_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        n = 0
        for old, new in REPLACEMENTS:
            n += text.count(old)
        if n:
            hits.append((os.path.relpath(path, ROOT), n))
    return sorted(hits, key=lambda x: -x[1])


def apply_changes():
    changed, renamed = [], []
    for path in iter_text_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        new_text = text
        for old, new in REPLACEMENTS:
            new_text = new_text.replace(old, new)
        if new_text != text:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
            changed.append(os.path.relpath(path, ROOT))

    # 文件改名
    for src_rel, dst_rel in RENAME_FILES.items():
        src = os.path.join(ROOT, src_rel)
        dst = os.path.join(ROOT, dst_rel)
        if not os.path.exists(src):
            continue
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(src, dst)
        renamed.append("%s  ->  %s" % (src_rel, dst_rel))
    return changed, renamed


def main():
    ap = argparse.ArgumentParser(description="批量替换项目品牌标识")
    ap.add_argument("--apply", action="store_true", help="实际写盘（默认仅预览）")
    args = ap.parse_args()

    if not args.apply:
        hits = preview()
        print("预览：以下文件含有旧品牌标识（未做任何修改）\n")
        for rel, n in hits:
            print("  %-52s %d 处" % (rel, n))
        print("\n共 %d 个文件。加 --apply 执行替换。" % len(hits))
        return 0

    changed, renamed = apply_changes()
    print("已替换内容：%d 个文件" % len(changed))
    for rel in changed:
        print("   ", rel)
    print("\n已重命名文件：%d 个" % len(renamed))
    for rel in renamed:
        print("   ", rel)
    print("\n完成。请检查残余引用：grep -rn 旧品牌名 .")
    return 0


if __name__ == "__main__":
    sys.exit(main())
