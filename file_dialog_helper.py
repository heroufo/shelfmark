# -*- coding: utf-8 -*-
"""文件/目录选择对话框辅助脚本（由 app.py 以子进程方式调用）。

用法: pythonw.exe file_dialog_helper.py <输出文件路径> [file|folder]
- 默认 file：弹出「选择电子书文件」对话框
- folder：弹出「选择目录」对话框（批量导入用）
选中后把路径写入输出文件（UTF-8）；用户取消则不写文件。

说明：
- 使用 pythonw.exe 运行，避免弹出多余的控制台窗口
- 使用独立输出文件而非 stdout，规避无控制台进程的编码/管道问题
- 本机单用户工具，仅用于弹出系统原生选择框
"""

import sys
import tkinter as tk
from tkinter import filedialog


def main():
    if len(sys.argv) < 2:
        return
    out_file = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "file"

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # 让对话框显示在最上层

    if mode == "folder":
        path = filedialog.askdirectory(title="选择电子书目录")
    else:
        path = filedialog.askopenfilename(
            title="选择电子书文件",
            filetypes=[
                ("电子书文件", "*.pdf *.epub *.mobi"),
                ("所有文件", "*.*"),
            ],
        )
    root.destroy()

    if path:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(path)


if __name__ == "__main__":
    main()
