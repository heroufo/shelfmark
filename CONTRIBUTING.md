# 贡献指南

感谢你有兴趣改进 Shelfmark！本文档说明如何搭建环境、提交修改。

## 代码结构（分层约定）

```
app.py                    入口：创建 Flask app、注册路由、启动逻辑（约 300 行）
shelfmark/                内部模块包
  paths.py                运行模式与目录常量（「双基地」：打包版 / 源码版）
  utils.py                通用纯函数（数值 / 标签 / 文本 / 时间）
  storage.py              书库读写、原子保存、配置、站点目录解析
  nationality.py          作者国籍（按文件名解析，离线）
  metadata.py             在线元数据（豆瓣）抓取与解析
  dialogs.py              系统原生文件 / 目录对话框、默认程序打开
  books.py                排序、表单校验与构建、书架规则、标签统计
  publishing.py           在线发布的数据差异计算
  views/                  路由层，按领域分模块
export_data.py            导出「净化版」数据到在线只读浏览站
file_dialog_helper.py     源码版：以子进程弹系统文件对话框（tkinter）
make_icon.py / make_autostart.py   图标生成 / 开机自启脚本生成
shelfmark.spec            PyInstaller 打包配置（单文件 exe）
start.bat / build_exe.bat Windows 一键启动 / 一键重新打包
templates/ static/        Jinja2 模板与本地化静态资源
tools/ tests/ docs/       开发辅助、测试、设计文档
data/                     【本地数据，不入库】书库 JSON、配置、日志
```

**依赖方向是单向的**（上层可依赖下层，反向不可）：

```
paths → utils → storage → nationality / metadata / dialogs → books → publishing
                                        ↘  views/*（唯一接触 Flask 的地方）
```

两条硬规则：

1. **新增路由请写进 `shelfmark/views/` 对应领域模块**，并在该模块的 `register(app)`
   里用 `app.add_url_rule(规则, 端点名, 函数)` 注册。
   端点名一旦被模板 `url_for()` 用到就**不能改**——`tests/test_routes.py` 会检查。
2. **不要为了让代码看起来整齐而缩进搬动函数体**：视图函数刻意保持在模块顶层，
   这样函数体里的多行字符串内容不会因为缩进而改变。

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
- 私有辅助函数用 `_` 前缀；跨模块共用的放对应领域模块，**不要复制粘贴**。
- 模板/前端：2 空格缩进，样式集中在 `templates/base.html`，避免引入 CDN。
- 提交前请依次通过：

```bash
python tools/check_imports.py --strict    # 静态检查：用了却没 import 的名字
python -m pytest                          # 单元测试（176 项，无需书库数据）
```

## 测试

四层，按需要选择：

```bash
# 1) 单元测试：不需要书库，CI 必跑
python -m pytest

# 2) 路由基线：端点名 / URL 规则 / 模板 url_for 完整性
python -m pytest tests/test_routes.py

# 3) 真实书库端到端（本机有 data/library.json 时）
python tests/regression_reallib.py        # 全部页面 GET
python tests/post_routes_check.py         # 全部写操作 POST，跑完自动还原数据

# 4) 手动验证（会真的弹出系统对话框，需人点一下）
python tests/manual_native_dialog.py
python tests/manual_exe_browse.py         # 需先打包 exe
```

> `post_routes_check.py` 会先备份 `data/library.json`，结束时无条件还原并校验 md5，
> 可以放心在本机真实书库上运行。
>
> 改动了「打包 / 对话框 / 路径基准」相关代码时，请额外跑一遍手动验证脚本 ——
> 自动化测试无法真正点选系统对话框。

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
