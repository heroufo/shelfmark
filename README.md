# 📚 Shelfmark · 私人书库

本地运行、零依赖服务的个人电子书管理器。用 Flask + 单个 JSON 文件管理你的藏书元数据，
自带封面墙、丛书分卷、书架归集、批量导入与在线元数据补全；也能打包成一个免安装的
`exe`，拷到任何 Windows 电脑双击即用。

> 名字取自图书馆学的 **shelfmark（索书号）** —— 给每本书一个位置，让它能被找到。

## ✨ 功能

**书库**

- 封面墙 / 表格双视图，可切换；支持分页（每页 108 项）
- 搜索：书名、副标题、作者、ISBN
- 筛选：标签（多选）、状态、星级、丛书；排序：入库时间、书名、作者、出版社、
  出版年、**页数**、评分、状态、格式（升降序）
- 丛书分组，同丛书按卷号升序浏览
- 批量操作：批量删除、批量打标签（追加 / 覆盖）、批量加入书架

**书籍详情**

- 杂志式排版：状态角标、格式胶囊、作者国籍徽标、评分
- **翻书导航**：上一本 / 第 N 本 / 共 M 本 / 下一本，按入库时间排序
- **一键补全元数据**：按 ISBN（或书名兜底）从在线书源补全作者、国籍、出版社、
  出版年、页数；只补空缺字段，不覆盖你已填内容
- 内容简介自动获取与手动刷新；相似图书推荐（基于元数据的内容相似度算法）
- 直接从浏览器下载书籍副本，或用系统默认程序打开本地文件

**书架**

- 普通书架：手动归集
- 智能书架：按规则自动归集（作者 / 出版社 / 标签 / 状态等条件）

**工具合集**（`/import` 一页六卡）

- 批量扫描导入：递归扫描文件夹，自动导入 `pdf / epub / mobi`，
  书名自动从文件名截取（`丑闻 - [日]远藤周作.epub` → 书名「丑闻」）；
  已存在的书自动跳过，不重复入库
- 作者国籍：按文件名标识批量解析（`[英]` → 英国；无标识默认中国，
  内置约 90 国缩写映射表）
- 标签统计：标签分布一览，点击即筛选
- 路径修正：换电脑 / 移动书库后按「旧前缀 → 新前缀」批量修复 `file_path`
- 备份 / 恢复：导出书库 JSON；上传 JSON 恢复（合并或覆盖，原库自动备份）

**统计与发布**

- 统计仪表盘：藏书量、状态分布、评分、标签、作者、出版社、年代等多维统计
- 一键发布：把「净化版」数据（剔除本机路径）导出到静态站点目录并
  `git push`，得到一个只读在线浏览站（如 GitHub Pages）

## 🚀 快速开始

```bash
git clone https://github.com/heroufo/shelfmark.git
cd shelfmark
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt     # 只有一个依赖：Flask
python app.py
```

浏览器打开 **http://127.0.0.1:5000** 。首次运行会自动创建 `data/library.json`（空库）。

Windows 用户也可以直接双击 **`启动图书馆.bat`**：后台静默启动、探测端口就绪后自动开浏览器。

**可选配置**（环境变量）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PORT` | `5000` | 监听端口 |
| `FLASK_DEBUG` | `1` | 设为 `0` 关闭调试与自动重载 |
| `SITE_DIR` | — | 在线浏览站目录（优先级高于 `data/config.json`） |
| `PUBLISH_DRY_RUN` | — | 设为 `1` 时「发布」只导出、不执行 git |
| `NO_BROWSER` | — | 打包版设为 `1` 可不自动开浏览器 |

## 📦 打包为免安装 exe

```bash
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean --distpath dist_exe shelfmark.spec
```

产物为 `dist_exe/` 便携目录，拷到任意 Windows 10/11 x64 即可运行（**目标机无需安装 Python**）：

```
dist_exe/
├── Shelfmark.exe       单文件主程序（约 13 MB，双击自动运行并打开浏览器）
├── data/library.json   书库数据（外置，方便备份 / 迁移）
├── covers/             封面图（外置）
└── 使用说明.txt
```

Windows 下也可以直接双击项目根目录的 **`一键重新打包.bat`**：生成图标 → 打包 →
把最新书库与封面同步进 `dist_exe/`，一条龙完成。

> **运行机制**：打包版区分两个路径基准 —— 可写数据在 **exe 同级目录**
> （`data/`、`covers/`、`app.log`），只读资源在 exe 内部（模板、样式、内置占位图）。
> 因此换电脑 = 拷贝 `exe + data + covers`；程序本身也不依赖系统 Python。
>
> 无控制台窗口运行，出错请看 `data/app.log`。

## 🗂 项目结构

```
.
├── app.py                    # Flask 主程序：路由、业务逻辑、JSON 存储
├── export_data.py            # 导出净化版数据到在线只读浏览站
├── file_dialog_helper.py     # 源码版：子进程弹系统文件对话框（tkinter）
├── shelfmark.spec            # PyInstaller 打包配置
├── make_icon.py              # Logo → exe 图标
├── make_autostart.py         # 生成 Windows 开机自启脚本（可选）
├── templates/                # Jinja2 模板（base.html 内含全部样式）
├── static/                   # 本地化 Bootstrap、Logo、默认占位图
│   ├── css/  js/             # 离线可用，无 CDN 依赖
│   ├── images/               # Logo 与默认封面（原创，代码绘制）
│   └── covers/               # 用户封面【不入库】
├── tools/                    # 开发辅助：画 Logo、改品牌名、开源体检
├── tests/                    # 端到端冒烟测试
├── docs/                     # 设计文档
└── data/                     # 【本地数据，不入库】书库 / 配置 / 日志
```

## 🔧 数据与配置

### `data/library.json`

```json
{
  "version": 1,
  "books": [ { "book_id": "…", "title": "…", "tags": ["…"], "status": "在读" } ],
  "shelves": []
}
```

| 字段 | 说明 |
| --- | --- |
| `book_id` | 唯一 ID（自动生成） |
| `title` / `subtitle` | 书名 / 副标题 |
| `author` / `author_nationality` | 作者 / 作者国籍 |
| `series` / `series_number` | 丛书名 / 卷号 |
| `publisher` / `publish_year` / `isbn` | 出版社 / 出版年 / ISBN |
| `pages` | 页数（`0` 表示未知） |
| `file_path` / `file_format` | 本地文件路径 / 格式 |
| `cover_path` | 封面文件名或 URL |
| `rating` | 评分 0–5 |
| `tags` / `status` | 标签列表 / 状态（未读·在读·已读·搁置） |
| `blurb` / `notes` | 内容简介 / 个人备注 |
| `added_time` | 入库时间 |

### `data/config.json`

```json
{
  "site_dir": "D:/path/to/your/library-web",
  "online_metadata": true
}
```

- `site_dir`：在线浏览站仓库路径（不填则默认取「与项目目录同级的 `library-web`」）
- `online_metadata`：设为 `false` 可**完全关闭**在线元数据抓取，纯离线运行

## 🔒 隐私与合规

本程序为**本地单机工具**，请特别注意以下几点：

1. **数据不出本机**：书库、封面、阅读记录全部保存在本地 `data/` 与 `static/covers/`，
   不向任何自建服务器上传。程序没有账号体系、没有遥测。
2. **公开仓库**：`data/` 与 `static/covers/` 已在 `.gitignore` 中排除 ——
   前者含个人藏书与**本机绝对路径**，后者封面为出版社 / 电商版权素材。
   克隆本项目后请勿把它们提交到公开仓库。
3. **在线元数据抓取**：`fetch_book_meta` / `fetch_book_blurb` 通过抓取
   豆瓣读书网页获取书名、作者、出版社、出版年、页数、简介。
   - 该站点未提供此类用途的官方公开 API，本功能**仅用于个人本地整理**；
   - 请勿用于批量商业抓取；高频请求会触发目标站点限流（需要等待一段时间恢复）；
   - 使用者应自行遵守目标网站的条款与 robots 约定；
   - 如不需要，把 `data/config.json` 的 `online_metadata` 设为 `false` 即可关闭。
4. **电子书文件**：程序只读写元数据。**删除书籍、批量导入都不会删除或移动你磁盘上的
   电子书文件**。
5. **封面**：请使用你有权使用的图片。仓库内不含任何第三方封面。

详细第三方组件授权见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 🧳 迁移到另一台电脑

**方式一：打包版（推荐，新机无需装 Python）**
把整个 `dist_exe/` 文件夹拷过去，双击 `Shelfmark.exe` 即可。

**方式二：源码版**
1. 复制整个项目文件夹到新电脑
2. `pip install -r requirements.txt`
3. `python app.py`

**方式三：只搬数据**
在新机装好程序后，到「工具合集」用「恢复书库」上传导出的 JSON（可选合并 / 覆盖）。
封面已统一保存为相对文件名，复制 `covers/` 目录即自动生效。

> 电子书本体需另行复制到新机可达的位置；若盘符或目录变了，
> 用「工具合集 → 路径修正」按前缀一键修复所有 `file_path`。

## ❓ 常见问题

**Q：端口被占用 / 打不开页面？**
源码版用 `PORT=5001 python app.py` 换端口；打包版会自动向后寻找可用端口，看 `data/app.log`。

**Q：书库 JSON 损坏了怎么办？**
程序会自动把它备份为 `library.json.bak` 并重建空库，不会崩溃。用「恢复书库」上传备份的
JSON 即可找回。

**Q：为什么批量豆瓣更新中途大量失败？**
触发了目标站点限流。等待一段时间后分批重试即可，已成功的书不受影响。

**Q：Windows Defender 报毒？**
未做代码签名的 PyInstaller 单文件程序常被误报，属正常现象，添加信任即可。

**Q：能多人同时用吗？**
本项目定位是单机单用户工具，数据是内存缓存 + 整文件写入，不适合多写并发。
如需多设备访问，建议放在你自己的内网环境并只做只读浏览。

## 🤝 贡献

欢迎提 Issue 与 PR：见 [CONTRIBUTING.md](CONTRIBUTING.md)。
提交前请跑一次 `python tools/audit_opensource.py`，确认没有把个人数据带进仓库。

## 📄 许可证

[MIT](LICENSE) © 2026 heroufo
