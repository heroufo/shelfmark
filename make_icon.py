# -*- coding: utf-8 -*-
"""生成打包用 exe 图标：把 static/images/shelfmark_logo.png 转为多尺寸 icon.ico。
用法: python make_icon.py
产物: build_exe/icon.ico
"""
import os
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "static", "images", "shelfmark_logo.png")
OUT_DIR = os.path.join(BASE, "build_exe")
OUT = os.path.join(OUT_DIR, "icon.ico")

img = Image.open(SRC)
if img.mode not in ("RGBA", "P", "LA"):
    img = img.convert("RGBA")
img = img.convert("RGBA")
# 居中裁剪为正方形（若原图非正方形），再缩放到 256
w, h = img.size
side = min(w, h)
img = img.crop(((w - side) // 2, (h - side) // 2,
                (w - side) // 2 + side, (h - side) // 2 + side))
img = img.resize((256, 256), Image.LANCZOS)

os.makedirs(OUT_DIR, exist_ok=True)
# ICO 支持多尺寸；Windows 从大到小挑选。透明通道保留。
img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                     (64, 64), (128, 128), (256, 256)])
print("icon ->", OUT)
