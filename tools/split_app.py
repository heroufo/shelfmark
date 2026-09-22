# -*- coding: utf-8 -*-
"""
app.py 拆分辅助工具（重构期间使用的一次性工具，完成后可删除）

职责：把 app.py 中的顶层符号按预定义划分搬运到 shelfmark/ 包的模块里，
并自动重算双向 import —— 避免手工复制粘贴出错。

用法：
    python tools/split_app.py --stage core1 --dry-run   # 预览
    python tools/split_app.py --stage core1 --apply     # 执行

设计要点：
1. 符号按 AST 精确定位（函数含装饰器、常量赋值），源码逐行切片，内容零改动
2. 生成新模块后自动分析其"自由名字"，据此推导需要的 import（标准库 / Flask / 项目内）
3. app.py 删除已搬走的符号，并自动重算它需要的项目内 import
4. --dry-run 只打印计划，不写盘
"""

import argparse
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(ROOT, "app.py")

# --------------------------------------------------------------------------
# 外部符号表：名字 → import 语句
# --------------------------------------------------------------------------
STDLIB_IMPORTS = {
    "json": "import json",
    "os": "import os",
    "platform": "import platform",
    "random": "import random",
    "re": "import re",
    "shutil": "import shutil",
    "ssl": "import ssl",
    "sys": "import sys",
    "subprocess": "import subprocess",
    "tempfile": "import tempfile",
    "uuid": "import uuid",
    "time": "import time",
    "logging": "import logging",
    "threading": "import threading",
    "webbrowser": "import webbrowser",
    "ctypes": "import ctypes",
    "socket": "import socket",
    "datetime": "from datetime import datetime",
    "urllib.parse": "import urllib.parse",
    "urllib.request": "import urllib.request",
}
FLASK_NAMES = ["Flask", "Response", "abort", "flash", "jsonify", "redirect",
               "render_template", "request", "send_file",
               "send_from_directory", "url_for"]
# 项目内模块的公开路径（用于生成 from ... import ...）
PROJECT_PREFIX = "shelfmark"

# --------------------------------------------------------------------------
# 阶段划分
# --------------------------------------------------------------------------
STAGES = {
    # ---- 阶段一：底层纯逻辑（零 Flask 依赖）----
    "core1": [
        {
            "module": "shelfmark/paths.py",
            "doc": "运行模式、目录常量与全局配置项。\n\n"
                   "本模块是「双基地」设计的落点：\n"
                   "  - 打包版（PyInstaller onefile）：RUNTIME_DIR = exe 所在目录（可写数据区），\n"
                   "    RES_DIR = exe 内部解压区（只读内置资源）\n"
                   "  - 源码版：两者都指向项目目录，行为与原实现完全一致\n"
                   "不含任何 Flask 依赖，所有模块都可以安全 import 它。",
            "line_ranges": [(40, 96)],
            "symbols": [],
            # 搬运后必须修正的基准路径：本文件位于 shelfmark/ 子目录，
            # 项目根应为包的上一级，否则 data/ 与 covers/ 会落到包目录里
            "patches": [(
                "    RUNTIME_DIR = RES_DIR = os.path.dirname(os.path.abspath(__file__))",
                "    RUNTIME_DIR = RES_DIR = os.path.dirname(\n"
                "        os.path.dirname(os.path.abspath(__file__)))",
            )],
        },
        {
            "module": "shelfmark/utils.py",
            "doc": "通用工具函数：数值/标签/格式归一化、文本清洗、时间戳。\n"
                   "纯函数，无 Flask、无副作用，可独立单元测试。",
            "symbols": [
                "now_str", "safe_num", "normalize_tags", "guess_format",
                "title_from_filename", "_strip_html", "_truncate_cn",
                "status_class", "file_exists",
            ],
        },
        {
            "module": "shelfmark/storage.py",
            "doc": "书库元数据持久化：加载、原子保存、配置读写、站点目录解析。\n\n"
                   "保存采用四级兜底链（见 _atomic_replace），兼容受限文件系统：\n"
                   "  ① os.replace 重试 → ② copy2 复制覆盖 → ③ 备份后重建 → ④ .recover + 报错\n"
                   "损坏的数据文件会自动备份为 .bak 并重建空库，不让程序崩溃。",
            "symbols": [
                "ensure_data_dir", "load_config", "save_config", "get_site_dir",
                "online_metadata_enabled", "load_data", "save_data",
                "_atomic_replace", "get_book",
            ],
        },
    ],
    # ---- 阶段二：领域逻辑（国籍 / 豆瓣元数据 / 对话框 / 书籍辅助）----
    "core2": [
        {
            "module": "shelfmark/nationality.py",
            "doc": "作者国籍判定。\n\n"
                   "设计取向：**不依赖任何在线数据源**，直接按文件名中的\n"
                   "国家标记（如 `[英]阿加莎·克里斯蒂.pdf`）本地解析，秒级完成、无风控风险。\n"
                   "无标记或标记无法识别时判定为中国。",
            "symbols": [
                "_NATIONALITY_MAP", "_parse_nationality",
                "nationality_from_filename", "_count_nationalities", "_nat_stats",
            ],
        },
        {
            "module": "shelfmark/metadata.py",
            "doc": "在线元数据获取（数据源：豆瓣）。\n\n"
                   "仅用于补全书籍元数据（作者/国籍/出版社/出版年/页数/简介），\n"
                   "**只填空字段、不覆盖已有值**。可通过 data/config.json 的\n"
                   "online_metadata=false 完全关闭（见 storage.online_metadata_enabled），\n"
                   "关闭后所有抓取入口立即短路、不发任何网络请求。",
            "symbols": [
                "_DOUBAN_UA", "_http_get_text", "fetch_book_blurb",
                "_parse_subject_info", "fetch_book_meta", "_fetch_meta_by_title",
                "refresh_book_blurb",
            ],
        },
        {
            "module": "shelfmark/dialogs.py",
            "doc": "系统原生对话框与「用默认程序打开文件」。\n\n"
                   "两种实现路径并存，按运行模式自动选择：\n"
                   "  - 源码版：子进程调用带 tkinter 的系统 pythonw 执行 file_dialog_helper.py\n"
                   "  - 打包版：ctypes 直接调用 Windows 原生 API（GetOpenFileNameW /\n"
                   "    SHBrowseForFolderW），目标机器无需安装 Python\n"
                   "取消失败一律返回 None，绝不抛异常给上层。",
            "symbols": [
                "_DIALOG_PYTHON_CACHE", "_find_dialog_python",
                "open_file_with_default_app", "pick_file_dialog",
                "pick_folder_dialog", "_pick_dialog", "_native_log",
                "_native_dialog", "_native_pick_folder", "_native_pick_file",
            ],
        },
        {
            "module": "shelfmark/books.py",
            "doc": "书籍领域逻辑：排序配置、相似推荐、表单校验与构建、封面地址、\n"
                   "书架规则与标签统计。\n"
                   "本模块不含路由，视图层与测试都直接调用这里的函数。",
            "symbols": [
                "SORTABLE_FIELDS", "LEGACY_SORT", "recommend_related",
                "validate_book_form", "build_book_from_form", "form_values_from",
                "cover_url", "_tag_stats", "_ensure_shelves", "shelf_members",
                "shelf_rule_text",
            ],
        },
        {
            "module": "shelfmark/publishing.py",
            "doc": "在线只读浏览站（GitHub Pages）发布支持：发布状态读写、\n"
                   "书籍指纹与新旧数据差异统计。\n"
                   "实际的 git 命令与路由入口在视图层，这里只做纯数据计算。",
            "symbols": [
                "_read_publish_state", "_save_publish_state",
                "_book_sig", "_diff_books",
            ],
        },
    ],
}


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def read_app():
    with open(APP_PATH, encoding="utf-8") as f:
        return f.read()


def top_nodes(src):
    """顶层符号表：name -> node；同时支持多目标赋值（x = y = ... 取第一个名字）"""
    table = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            table[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    table[t.id] = node
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            table[node.target.id] = node
    return table


def node_span(node):
    """返回 (起始行, 结束行)，1-based 闭区间；含装饰器"""
    start = node.lineno
    if getattr(node, "decorator_list", None):
        start = min(d.lineno for d in node.decorator_list)
    return start, node.end_lineno


def segment(lines, node):
    a, b = node_span(node)
    return "\n".join(lines[a - 1:b])


def free_names(src):
    """返回源码中「需要从外部引入」的自由名字集合。

    用 ast.walk 递归收集定义（含 if 分支赋值与函数内局部变量），
    这样局部变量不会被误判为需要 import 的外部名字。
    """
    tree = ast.parse(src)
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            for a in getattr(node.args, "args", []) if isinstance(node, ast.FunctionDef) else []:
                defined.add(a.arg)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        defined.add(sub.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
    return used - defined


def render_imports(names, symbol_home, indent=""):
    """把外部名字渲染成 import 语句块。
    symbol_home: {名字: 'shelfmark.xxx'} 项目内符号归属"""
    lines = []
    std = sorted(STDLIB_IMPORTS[n] for n in names if n in STDLIB_IMPORTS)
    seen = set()
    for s in std:
        if s not in seen:
            lines.append(s)
            seen.add(s)
    flask = sorted(n for n in names if n in FLASK_NAMES)
    if flask:
        if len(flask) <= 4:
            lines.append("from flask import " + ", ".join(flask))
        else:
            body = ",\n".join("    " + n for n in flask)
            lines.append("from flask import (\n" + body + ",\n)")
    by_mod = {}
    for n in names:
        mod = symbol_home.get(n)
        if mod:
            by_mod.setdefault(mod, []).append(n)
    if by_mod:
        if lines:
            lines.append("")
        for mod in sorted(by_mod):
            syms = sorted(by_mod[mod])
            if len(syms) <= 3 and sum(len(s) for s in syms) < 46:
                lines.append("from %s import %s" % (mod, ", ".join(syms)))
            else:
                body = ",\n".join("    " + s for s in syms)
                lines.append("from %s import (\n%s,\n)" % (mod, body))
    unknown = sorted(n for n in names
                     if n not in STDLIB_IMPORTS and n not in FLASK_NAMES
                     and n not in symbol_home)
    return lines, unknown


def scan_package_home():
    """扫描 shelfmark/ 包内已有模块，返回 {符号名: 模块路径} 归属表"""
    home = {}
    pkg = os.path.join(ROOT, PROJECT_PREFIX)
    if not os.path.isdir(pkg):
        return home
    for root, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            path = os.path.join(root, fn)
            mod = os.path.relpath(path, ROOT).replace(os.sep, ".")[:-3]
            with open(path, encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read())
                except SyntaxError:
                    continue
            for node in tree.body:            # 只扫顶层定义，避免把局部变量误当符号
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    home.setdefault(node.name, mod)
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            home.setdefault(t.id, mod)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    home.setdefault(node.target.id, mod)
                elif isinstance(node, ast.If):
                    # 常量块里的分支赋值（如 if IS_FROZEN: X = ...）
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Assign):
                            for t in sub.targets:
                                if isinstance(t, ast.Name):
                                    home.setdefault(t.id, mod)
    return home


def compress_blanks(text, max_blank=2):
    """压缩连续空行"""
    out, blank = [], 0
    for line in text.splitlines():
        if line.strip() == "":
            blank += 1
            if blank > max_blank:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# 执行一个阶段
# --------------------------------------------------------------------------
def run_stage(stage, apply_changes):
    plan = STAGES[stage]
    src = read_app()
    lines = src.splitlines()
    table = top_nodes(src)

    # 1) 收集要搬运的内容
    moved, removals = {}, []          # removals: (start, end) 1-based 闭区间
    for entry in plan:
        chunks = []
        for a, b in entry.get("line_ranges", []):
            chunks.append("\n".join(lines[a - 1:b]))
            removals.append((a, b))
        for name in entry.get("symbols", []):
            node = table.get(name)
            if node is None:
                print("  !! 找不到符号 %s" % name)
                return 1
            a, b = node_span(node)
            chunks.append(segment(lines, node))
            removals.append((a, b))
        moved[entry["module"]] = chunks

    # 2) 合并删除区间（先按起点排序，再合并重叠/相邻区间；
    #    同时吞掉紧邻上方的连续注释行，避免留下孤立注释）
    def extend_up(a):
        i = a - 2                                   # 0-based 上一行
        while i >= 0:
            s = lines[i].strip()
            if s.startswith("#") and not s.startswith("#!"):
                i -= 1
                continue
            break
        return i + 2                                # 转回 1-based

    spans = []
    for a, b in sorted(removals, key=lambda x: (x[0], x[1])):
        a = extend_up(a)
        if spans and a <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])

    # 3) 新的项目内符号归属表（供 import 推导）
    #    先扫描 shelfmark/ 包内已存在的模块（前面阶段搬过去的符号），
    #    再叠加本阶段要搬的符号 —— 否则新模块引用旧模块符号时生成不出 import
    home = scan_package_home()
    for entry in plan:
        mod = entry["module"].replace("/", ".")[:-3]
        for name in entry.get("symbols", []):
            home[name] = mod
        for a, b in entry.get("line_ranges", []):
            seg = "\n".join(lines[a - 1:b])
            # 递归收集：常量块里可能有 if/else 分支赋值（如 IS_FROZEN 下的
            # RUNTIME_DIR / COVER_UPLOAD_DIR），不能只看顶层节点
            for node in ast.walk(ast.parse(seg)):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    home[node.name] = mod
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            home[t.id] = mod
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    home[node.target.id] = mod

    # 4) 生成新模块
    written = []
    for entry in plan:
        mod_path = os.path.join(ROOT, entry["module"])
        mod_name = entry["module"].replace("/", ".")[:-3]
        body = "\n\n\n".join(moved[entry["module"]])
        names = free_names(body)
        # 排除本模块自身定义的符号（否则会生成自引用 import → 循环导入）
        names = {n for n in names if home.get(n) != mod_name}
        imp, unknown = render_imports(names, home)
        if unknown:
            print("  (提示) %s 中未解析的名字: %s" % (entry["module"], unknown))
        header = ('# -*- coding: utf-8 -*-\n'
                  '"""%s"""\n' % entry["doc"])
        text = header + "\n"
        if imp:
            text += "\n".join(imp) + "\n\n\n"
        text += compress_blanks(body)
        # 应用该模块的定向修正（如路径基准），修正失败直接报错而不是静默放过
        for old, new in entry.get("patches", []):
            if old not in text:
                print("  !! %s 未找到待修正片段：%r" % (entry["module"], old[:60]))
                return 1
            text = text.replace(old, new, 1)
        written.append((mod_path, text))
        print("  + %s  (%d 行)" % (entry["module"], text.count("\n")))

    # 5) 重算 app.py
    keep = []
    for idx, line in enumerate(lines, 1):
        if any(a <= idx <= b for a, b in spans):
            continue
        keep.append(line)
    new_app = compress_blanks("\n".join(keep))

    # app.py 需要从新模块 import 什么
    need = free_names(new_app)
    need = {n for n in need if n in home}
    app_imports, _ = render_imports(need, home)
    if app_imports:
        marker = "# ---------------------------------------------------------------------------\n# 项目内模块\n"
        block = (marker +
                 "# 拆分后的内部模块（行为与原单文件实现完全一致）\n"
                 "# ---------------------------------------------------------------------------\n"
                 + "\n".join(app_imports) + "\n")
        # 插到本地模块 import（import export_data）之后
        anchor = "import export_data\n"
        if anchor in new_app:
            new_app = new_app.replace(
                anchor, anchor + "\n" + block, 1)
        else:
            new_app = new_app.replace(
                'from flask import', block + "\nfrom flask import", 1)

    # 6) 校验：被搬走的符号必须已从 app.py 消失
    #    （区间合并出错时会出现「生成了模块但 app.py 仍保留定义」的假成功）
    left_top = set(top_nodes(new_app))
    dup = []
    for entry in plan:
        for name in entry.get("symbols", []):
            if name in left_top:
                dup.append(name)
        for a, b in entry.get("line_ranges", []):
            seg = "\n".join(lines[a - 1:b])
            for node in ast.parse(seg).body:
                nm = None
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    nm = node.name
                elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                    nm = node.targets[0].id
                if nm and nm in left_top:
                    dup.append(nm)
    if dup:
        print("\n!! 校验失败：以下符号已生成新模块，但仍留在 app.py 中（代码重复）：")
        print("   " + ", ".join(sorted(set(dup))))
        print("   本次不写入任何文件，请检查 split_app.py 的区间合并逻辑。")
        return 1

    if not apply_changes:
        print("\n[dry-run] app.py: %d 行 → %d 行（减少 %d 行）"
              % (len(lines), new_app.count("\n"), len(lines) - new_app.count("\n")))
        print("[dry-run] 生成 import 块：")
        for l in app_imports:
            print("     " + l)
        return 0

    for mod_path, text in written:
        os.makedirs(os.path.dirname(mod_path), exist_ok=True)
        with open(mod_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    with open(APP_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_app)
    print("\n[apply] 已写入 %d 个模块；app.py %d 行 → %d 行"
          % (len(written), len(lines), new_app.count("\n")))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply == a.dry_run:
        print("请指定 --dry-run 或 --apply 之一")
        return 2
    print("=== 阶段 %s ===" % a.stage)
    return run_stage(a.stage, a.apply)


if __name__ == "__main__":
    sys.exit(main())
