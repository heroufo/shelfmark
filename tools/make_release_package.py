# -*- coding: utf-8 -*-
"""组装「下载即用」的 Windows 发行包（不含任何个人数据）。

用法（在项目根目录执行）::

    python tools/make_release_package.py
    python tools/make_release_package.py --exe dist_exe/Shelfmark.exe --out-dir dist_release
    python tools/make_release_package.py --keep-staging      # 保留暂存目录便于排查

产物::

    dist_release/Shelfmark-v1.1.1-win64.zip
        Shelfmark-v1.1.1-win64/
            Shelfmark.exe            主程序（双击运行）
            使用说明.txt              终端用户文档
            LICENSE                   MIT 许可证（分发必须附带）
            THIRD_PARTY_NOTICES.md    第三方组件声明
            data/                     空目录 —— 首次运行时自动填充
            covers/                   空目录 —— 首次运行时自动填充

设计要点
--------
1. **白名单复制**：只复制上面列出的文件，其余一律不碰。因此哪怕
   ``dist_exe/`` 里同时躺着你的私人书库，也不会被误打包。
2. **反向扫描兜底**：复制完成后扫描暂存目录，一旦发现 ``*.json``（
   library.json / config.json）、封面图片、``*.log`` 等个人数据，立即
   中止并报错。这是为了防止将来有人改动白名单时把私人数据带出去。
3. **可重复执行**：同名 zip 会被覆盖，不依赖任何外部状态。
"""
import sys

# Windows consoles default to cp1252; without this, any print() of CJK
# text raises UnicodeEncodeError and aborts the script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 白名单：允许进入发行包的文件（源路径相对项目根 -> 包内文件名）
# ---------------------------------------------------------------------------
ALLOWED_FILES = [
    ("packaging/使用说明.txt", "使用说明.txt"),
    ("LICENSE", "LICENSE"),
    ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
]

# 包内需要创建的（空）目录
EMPTY_DIRS = ["data", "covers"]

# 反向扫描：这些扩展名一旦出现在暂存目录 = 私人数据泄漏，直接中止
FORBIDDEN_EXTS = {
    ".json", ".log", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg",
}
# 允许出现的例外（白名单内文件不会命中上面的扩展名，这里留作将来扩展）
FORBIDDEN_ALLOW = set()


def say(msg=""):
    print(msg, flush=True)


def read_app_version():
    """从 shelfmark/paths.py 提取 APP_VERSION（不 import，避免拉起整个包）。"""
    path = os.path.join(PROJECT, "shelfmark", "paths.py")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise SystemExit("无法读取 %s：%s" % (path, exc))
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        raise SystemExit("未能在 shelfmark/paths.py 中找到 APP_VERSION")
    return m.group(1)


def sha256_of(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def human(nbytes):
    if nbytes < 1024:
        return "%d B" % nbytes
    if nbytes < 1024 * 1024:
        return "%.1f KB" % (nbytes / 1024.0)
    return "%.2f MB" % (nbytes / 1024.0 / 1024.0)


def scan_for_private_data(staging, arc_root):
    """在暂存目录里找个人数据；返回命中的相对路径列表。"""
    hits = []
    root = os.path.join(staging, arc_root)
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), staging)
            ext = os.path.splitext(name)[1].lower()
            if ext in FORBIDDEN_EXTS and rel not in FORBIDDEN_ALLOW:
                hits.append(rel)
    return hits


def build(exe_path, out_dir, version, keep_staging, app_name="Shelfmark"):
    if not os.path.isfile(exe_path):
        raise SystemExit(
            "找不到主程序：%s\n"
            "请先打包：python -m PyInstaller --noconfirm --distpath dist_exe shelfmark.spec\n"
            "（或双击 build_exe.bat）" % exe_path)

    pkg_name = "%s-v%s-win64" % (app_name, version)
    staging = tempfile.mkdtemp(prefix="shelfmark_pkg_")
    arc_root = pkg_name

    say("== 组装 %s ==" % pkg_name)
    say("[1/5] 复制主程序")
    dest_exe = os.path.join(staging, arc_root, app_name + ".exe")
    os.makedirs(os.path.dirname(dest_exe), exist_ok=True)
    shutil.copy2(exe_path, dest_exe)
    say("      %s  (%s)" % (app_name + ".exe", human(os.path.getsize(dest_exe))))

    say("[2/5] 复制文档与许可证")
    copied = [app_name + ".exe"]
    for src_rel, dest_name in ALLOWED_FILES:
        src = os.path.join(PROJECT, src_rel)
        if not os.path.isfile(src):
            say("      ! 跳过（源文件不存在）：%s" % src_rel)
            continue
        dst = os.path.join(staging, arc_root, dest_name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dest_name)
        say("      %s" % dest_name)

    say("[3/5] 创建空数据目录（首次运行时自动填充）")
    for d in EMPTY_DIRS:
        os.makedirs(os.path.join(staging, arc_root, d), exist_ok=True)
        say("      %s/" % d)

    say("[4/5] 安全扫描（反向检查私人数据）")
    hits = scan_for_private_data(staging, arc_root)
    if hits:
        say("      !! 发现疑似个人数据，已中止，不会生成 zip：")
        for h in hits:
            say("         %s" % h)
        shutil.rmtree(staging, ignore_errors=True)
        raise SystemExit(2)
    say("      OK —— 未发现书库 / 封面 / 日志等个人数据")

    say("[5/5] 打包 zip")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, pkg_name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 显式写入空目录条目，否则解压后 data/ 与 covers/ 会消失
        for d in EMPTY_DIRS:
            info = zipfile.ZipInfo("%s/%s/" % (arc_root, d))
            info.flag_bits |= 0x800          # 声明文件名是 UTF-8（中文名必须）
            info.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(info, b"")
        for dirpath, _dirnames, filenames in os.walk(os.path.join(staging, arc_root)):
            for name in filenames:
                full = os.path.join(dirpath, name)
                arc = os.path.join(
                    arc_root, os.path.relpath(full, os.path.join(staging, arc_root)))
                arc = arc.replace(os.sep, "/")
                info = zipfile.ZipInfo.from_file(full, arc)
                info.flag_bits |= 0x800
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as src, zf.open(info, "w") as dst:
                    shutil.copyfileobj(src, dst)

    if not keep_staging:
        shutil.rmtree(staging, ignore_errors=True)

    say("")
    say("== 完成 ==")
    say("产物   : %s" % zip_path)
    say("大小   : %s" % human(os.path.getsize(zip_path)))
    say("SHA256 : %s" % sha256_of(zip_path))
    say("")
    say("包内清单：")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            kind = "<DIR>" if info.is_dir() else human(info.file_size)
            say("  %-10s %s" % (kind, info.filename))
    if keep_staging:
        say("")
        say("暂存目录保留在：%s" % staging)
    return zip_path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="组装不含个人数据的 Shelfmark Windows 发行包")
    ap.add_argument("--exe", default=os.path.join("dist_exe", "Shelfmark.exe"),
                    help="已打包的单文件 exe 路径（默认 dist_exe/Shelfmark.exe）")
    ap.add_argument("--out-dir", default="dist_release",
                    help="zip 输出目录（默认 dist_release）")
    ap.add_argument("--version", default=None,
                    help="覆盖版本号（默认从 shelfmark/paths.py 读取）")
    ap.add_argument("--keep-staging", action="store_true",
                    help="保留临时暂存目录，便于排查")
    args = ap.parse_args(argv)

    exe = args.exe if os.path.isabs(args.exe) else os.path.join(PROJECT, args.exe)
    out_dir = args.out_dir if os.path.isabs(args.out_dir) else os.path.join(PROJECT, args.out_dir)
    version = args.version or read_app_version()

    build(exe, out_dir, version, args.keep_staging)
    return 0


if __name__ == "__main__":
    sys.exit(main())
