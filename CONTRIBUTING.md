# 贡献指南

感谢你有兴趣改进 Shelfmark！本文档说明如何搭建环境、提交修改。

## 目录结构

```
.
├── app.py                    # Flask 主程序（路由 + 业务逻辑 + 存储）
├── export_data.py            # 导出「净化版」数据到在线只读浏览站
├── file_dialog_helper.py     # 源码版：以子进程弹系统文件对话框（tkinter）
├── make_icon.py              # 由 Logo 生成 exe 图标
├── make_autostart.py         # 生成开机自启 VBS（Windows）
├── shelfmark.spec            # PyInstaller 打包配置（单文件 exe）
├── templates/                # Jinja2 模板（base.html 内含全部样式）
├── static/                   # 本地化 Bootstrap、图标、默认封面；covers/ 为用户封面
├── tools/                    # 开发辅助脚本（画 Logo、改品牌名、开源体检）
├── tests/                    # 端到端测试脚本
├── docs/                     # 设计文档
└── data/                     # 【本地数据，不入库】书库 JSON、配置、日志
```

## 开发环境

```bash
git clone https://github.com/<your-name>/shelfmark.git
cd shelfmark
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # 运行时依赖（仅 Flask）
python app.py                          # → http://127.0.0.1:5000
```

打包为 exe / 生成图标时再装开发依赖：

```bash
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean --distpath dist_exe shelfmark.spec
```

## 数据与本机路径

- 程序所有可写数据都在 `data/`（首次运行自动创建）。
- 路径基准由 `app.py` 顶部的「双基地」逻辑决定，**不要写死绝对路径**：
  - 源码运行：`RUNTIME_DIR = RES_DIR = 项目目录`
  - 打包运行（`sys.frozen`）：`RUNTIME_DIR` = exe 所在目录，`RES_DIR` = 解包临时目录
- 在线发布站点的路径走 `data/config.json` 的 `site_dir` 或环境变量 `SITE_DIR`，
  默认约定为「与项目目录同级的 `library-web`」。

## 代码风格

- Python：4 空格缩进，PEP 8，模块/函数写中文 docstring（本项目中文注释为主）。
- 模板/前端：2 空格缩进，样式集中在 `templates/base.html`，避免引入 CDN。
- 提交前请确保 `python -m py_compile app.py export_data.py` 通过。

## 测试

```bash
# 核心端点端到端（需先有 data/library.json，可空库）
python tests/test_native_dialog.py     # 校验系统原生文件/目录对话框（会短暂弹窗）
python tests/test_exe_browse.py        # 校验打包版 exe 的「浏览…」链路（需先打包）
python tools/audit_opensource.py       # 开源就绪度自检（隐私/合规/结构）
```

> 说明：本项目的自动化测试直接驱动真实对话框与真实 HTTP 接口，
> 属「冒烟测试」性质。欢迎补充基于 `app.test_client()` 的单元测试。

## 提交规范

- 分支：从 `main` 切出 `feat/xxx`、`fix/xxx`。
- 提交信息：祈使句 + 简明说明，建议英文，例如
  `fix: native folder dialog returns None on 64-bit PIDL`。
- 一个 PR 只做一件事；标题写清「改了什么 / 为什么」。
- **不要提交**：`data/`（个人书库）、`static/covers/`（版权封面）、
  `dist_exe/`、`build/`（构建产物）—— 已在 `.gitignore` 中排除。

## 隐私红线（务必遵守）

提交 PR 前请检查：

1. 不引入任何真实个人数据（书库内容、绝对路径、用户名、邮箱、token）。
2. 新增外部请求（爬虫 / API）必须有明确用途说明、超时与错误兜底，
   并在 README 的「隐私与合规」中声明。
3. 不引入带商标风险的名称、Logo 或素材。

## 行为准则

友善、就事论事。讨论技术方案时欢迎直接指出问题，但请针对代码而非人。
