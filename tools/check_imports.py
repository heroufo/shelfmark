# -*- coding: utf-8 -*-
"""
静态 import 完整性检查。

Python 是动态语言：模块里引用了没 import 的名字，编译期不会报错，
只有那一行代码真的跑到才抛 NameError —— 拆分模块时极易踩坑。
本脚本用 AST 分析每个源文件的「自由名字」，逐个确认它有明确来源：

    ① 本文件内定义   ② 已 import   ③ Python 内置   ④ 标注的已知动态名字

任何既不属于以上四类的名字都会被报出来。可作为 CI 检查项。

用法：
    python tools/check_imports.py             # 检查全部（app.py + shelfmark/）
    python tools/check_imports.py --strict    # 有可疑名字时返回非零退出码
    python tools/check_imports.py --verbose   # 额外打印每个文件的自由名字清单

在 GitHub Actions 上运行时，会把诊断信息以 ::error:: / ::notice:: 注解输出，
便于在不登录、下载不了日志的情况下定位问题（注解可经公开 API 读取）。
"""

import argparse
import ast
import builtins
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 允许出现的动态/内置名字（运行环境注入或约定俗成）
ALLOWED = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
    "__builtins__", "self", "cls", "app",          # app 由 register(app) 传入
    "annotations",
}
BUILTINS = set(dir(builtins))
# 标准库模块名（Python 3.10+ 提供），用于识别「用了 urllib 却没 import」这类问题
STDLIB_NAMES = set(getattr(sys, "stdlib_module_names", ()))

ON_CI = os.environ.get("GITHUB_ACTIONS") == "true"


def annotate(level, text):
    """输出 GitHub Actions 注解（转义换行与百分号）。"""
    if not ON_CI:
        return
    payload = (str(text).replace("%", "%25")
               .replace("\r", "%0D").replace("\n", "%0A"))
    print("::%s::%s" % (level, payload))


def collect(path):
    """返回 (自由名字集合, 诊断信息)"""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)

    defined, imported, local_scopes = set(), set(), set()

    def note_target(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                defined.add(sub.id)
            elif isinstance(sub, ast.Tuple):
                note_target(sub)

    # 模块顶层：定义与 import
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                nm = (a.asname or a.name).split(".")[0]
                imported.add(nm)
                defined.add(nm)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                note_target(t)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Try):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        note_target(t)
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        note_target(t)

    # 函数级：参数与局部变量（这些不算自由名字）
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            local_scopes.add(node)
        if isinstance(node, ast.arg):
            local_scopes.add(node)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local_scopes.add(node)
        if isinstance(node, ast.ExceptHandler) and node.name:
            local_scopes.add(node)
        if isinstance(node, ast.comprehension) and isinstance(node.target, ast.Name):
            local_scopes.add(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for a in node.args.args:
                local_scopes.add(a)

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    # 名字若出现在函数内部作为参数/局部变量，则不是模块级自由名字
    local_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            local_names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local_names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_names.add(node.name)
            for a in node.args.args:
                local_names.add(a.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                local_names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local_names.add(node.name)

    free = {n for n in used
            if n not in defined and n not in BUILTINS and n not in ALLOWED
            and n not in local_names}
    return free, {"defined": defined, "imported": imported}


def scan_files():
    out = [os.path.join(ROOT, "app.py"), os.path.join(ROOT, "export_data.py")]
    pkg = os.path.join(ROOT, "shelfmark")
    for root, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if fn.endswith(".py"):
                out.append(os.path.join(root, fn))
    return [p for p in out if os.path.isfile(p)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--verbose", action="store_true",
                    help="打印每个文件的自由名字清单")
    args = ap.parse_args()

    files = scan_files()

    # 环境指纹：跨平台排查时最有用的一行
    fingerprint = ("python=%s platform=%s files=%d stdlib_names=%d root=%s"
                   % (sys.version.split()[0], sys.platform, len(files),
                      len(STDLIB_NAMES), ROOT))
    print("env: " + fingerprint)
    annotate("notice", "check_imports env: " + fingerprint)

    # 全局符号表：包内所有模块的顶层符号 + 项目根模块
    known = set()
    for path in files:
        with open(path, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError as e:
                rel = os.path.relpath(path, ROOT)
                print("语法错误 %s: %s" % (path, e))
                annotate("error", "syntax error in %s: %s" % (rel, e))
                return 1
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                known.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        known.add(t.id)
            elif isinstance(node, ast.If):
                # 常量块里的分支赋值（如 if IS_FROZEN: COVER_UPLOAD_DIR = ...）
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign):
                        for t in sub.targets:
                            if isinstance(t, ast.Name):
                                known.add(t.id)

    problems = 0
    for path in files:
        try:
            free, _ = collect(path)
        except SyntaxError as e:
            rel = os.path.relpath(path, ROOT)
            print("语法错误 %s: %s" % (path, e))
            annotate("error", "syntax error in %s: %s" % (rel, e))
            return 1
        unresolved = sorted(free)
        rel = os.path.relpath(path, ROOT)
        if unresolved:
            # 全局符号表（项目内）或标准库里有、但本文件没 import 的 → 一定漏了
            suspicious = [n for n in unresolved
                          if n in known or n in STDLIB_NAMES]
            unknown = [n for n in unresolved
                       if n not in known and n not in STDLIB_NAMES]
            if suspicious:
                problems += len(suspicious)
                print("!! %s" % rel)
                print("   漏 import（项目内已有同名符号）：%s" % ", ".join(suspicious))
                reason = []
                for n in suspicious:
                    where = []
                    if n in known:
                        where.append("known")
                    if n in STDLIB_NAMES:
                        where.append("stdlib")
                    reason.append("%s[%s]" % (n, "+".join(where)))
                annotate("error", "%s 漏 import: %s" % (rel, " ".join(reason)))
            if unknown:
                print("   ? %s  未识别名字：%s" % (rel, ", ".join(unknown)))
            if args.verbose or ON_CI:
                annotate("notice", "%s free=%s" % (rel, ",".join(unresolved)))

    print("-" * 60)
    if problems:
        print("发现 %d 处漏 import，请修复。" % problems)
        annotate("error", "check_imports: %d unresolved name(s) treated as missing imports"
                 % problems)
        return 1 if args.strict else 0
    print("import 完整性检查通过 ✓")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        annotate("error", "check_imports crashed: " + tb)
        sys.exit(3)
