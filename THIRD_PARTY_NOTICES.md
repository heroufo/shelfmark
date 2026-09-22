# 第三方组件与素材声明

本项目（Shelfmark）以 MIT 许可证开源，同时使用了以下第三方组件与资源。
分发本项目（含打包后的可执行文件）时，请一并保留本声明。

## 运行依赖

| 组件 | 用途 | 许可证 | 说明 |
|---|---|---|---|
| [Flask](https://flask.palletsprojects.com/) | Web 框架 | BSD-3-Clause | 唯一运行时依赖 |
| [Bootstrap](https://getbootstrap.com/) | 前端 UI 框架 | MIT | 已本地化于 `static/css`、`static/js`，无 CDN 依赖 |

## 打包 / 开发依赖（`requirements-dev.txt`）

| 组件 | 用途 | 许可证 |
|---|---|---|
| [PyInstaller](https://pyinstaller.org/) | 打包为单文件可执行程序 | GPL-2.0-or-later，附 Bootloader 例外条款（允许打包专有/其他许可程序） |
| [Pillow](https://python-pillow.org/) | 生成项目图标 | MIT-CMU |

> PyInstaller 的 Bootloader 例外条款允许将任何许可的程序打包为可执行文件，
> 因此打包后的产物不受 GPL 传染。详见其 `COPYING.txt`。

## 项目自有素材

- 项目 Logo（`static/images/shelfmark_logo.png`）由 `tools/make_logo.py` 以代码绘制生成，
  属本项目原创，随 MIT 许可证一并授权。
- 默认封面占位图（`static/images/default_cover.svg`）为本项目原创 SVG。

## 未随仓库分发的内容

- **书籍封面图片**（`static/covers/`）：来自各出版社 / 电商平台的版权素材，
  仅供本地个人使用，已通过 `.gitignore` 排除，不在公开仓库中。
  使用本项目时请自行准备封面，并遵守相应权利方的使用条款。

## 外部数据源

- **豆瓣读书**（`search.douban.com`）：`fetch_book_meta` 等函数通过网页抓取
  获取图书元数据（书名 / 作者 / 出版社 / 出版年 / 页数 / 简介）。
  - 豆瓣未提供此类用途的公开官方 API，此功能仅用于**个人本地学习与整理**。
  - 请勿用于批量商业抓取；高频请求会触发目标站点的访问限制。
  - 使用者应自行遵守目标网站的服务条款与 robots 约定。
  - 元数据抓取功能可通过配置关闭，详见 README「隐私与合规」。

## 商标说明

项目名称 `Shelfmark` 取自图书馆学的通用术语（索书号 / 书架标记），
属描述性词汇，与任何商业品牌无关；本项目不是任何软件产品的官方版本，
也未获得任何第三方厂商的赞助或背书。
