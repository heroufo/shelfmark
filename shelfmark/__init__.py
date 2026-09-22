# -*- coding: utf-8 -*-
"""
Shelfmark 内部模块包。

本包从早期的单文件 `app.py` 拆分而来，目的是让业务逻辑可以被独立导入和
单元测试，而不必启动 Flask。**除 `views/` 之外，本包不依赖 Flask。**

分层约定
--------
依赖方向是单向的（上层可依赖下层，反向不可）::

    paths → utils → storage → nationality / metadata / dialogs → books → publishing
                                                     ↓
                                               views/*（唯一接触 Flask 的地方）

模块划分
--------
    paths        运行模式（打包版 / 源码版）与目录常量
    utils        通用纯函数：数值、标签、文本、时间
    storage      书库读写、原子保存、配置读取、站点目录解析
    nationality  作者国籍（按文件名解析，纯离线）
    metadata     在线元数据（豆瓣）抓取与解析
    dialogs      系统原生文件 / 目录对话框、默认程序打开
    books        排序、表单校验与构建、书架规则、标签统计
    publishing   在线发布所需的数据差异计算
    views/       路由层，按领域分模块；端点名与原单文件实现保持一致

改代码前请先读 `CONTRIBUTING.md` 的「代码结构（分层约定）」一节。
"""
