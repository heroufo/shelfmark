# -*- coding: utf-8 -*-
"""
生成项目 Logo（原创矢量风格，Pillow 绘制，无第三方素材、无商标风险）。

设计：三个高低错落的书脊立在书架板上 —— 对应 "Shelfmark"（索书号）的语义。
输出：static/images/shelfmark_logo.png（512x512 RGBA，四角透明）
用法：python tools/make_logo.py
"""

import os

from PIL import Image, ImageDraw

SIZE = 512
CORNER = 108                      # 外框圆角半径
GRAD_FROM = (99, 102, 241)        # #6366f1 靛蓝
GRAD_TO = (168, 85, 247)          # #a855f7 紫
WHITE = (255, 255, 255, 255)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "images", "shelfmark_logo.png")


def make_logo():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # 1) 圆角底 + 纵向渐变
    grad = Image.new("RGB", (1, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        grad.putpixel((0, y), tuple(
            int(GRAD_FROM[i] + (GRAD_TO[i] - GRAD_FROM[i]) * t) for i in range(3)))
    grad = grad.resize((SIZE, SIZE))

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=CORNER, fill=255)
    img.paste(grad, (0, 0), mask)

    # 2) 三本书脊（底部对齐）
    d = ImageDraw.Draw(img)
    bottom = 356
    for x0, top in ((153, 216), (227, 150), (301, 186)):
        d.rounded_rectangle([x0, top, x0 + 58, bottom], radius=16, fill=WHITE)

    # 3) 书架板
    d.rounded_rectangle([133, 352, 379, 374], radius=11, fill=WHITE)

    img.save(OUT)
    return OUT


if __name__ == "__main__":
    p = make_logo()
    print("logo ->", p, Image.open(p).size)
