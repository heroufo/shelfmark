# -*- coding: utf-8 -*-
"""
视图层（路由）包。

约定
----
每个模块都以 `def register(app)` 的形式对外提供注册入口，内部用
`app.add_url_rule(规则, 端点名, 视图函数)` 显式注册。这样做的好处：

1. **端点名完全可控**：与原单文件实现逐一对齐，模板里的 `url_for('index')`
   等写法一个字都不用改；
2. **视图函数留在模块顶层**：可以被单元测试或脚本直接调用，不必起 Flask；
3. **路由表一目了然**：每个模块的 `register()` 就是该领域的 URL 清单。

模块划分
--------
    system   模板上下文注入（书库统计、侧栏书架、发布状态）
    browse   主页 / 全部书籍 / 详情 / 作者、出版社、丛书聚合
    books    书籍增删改、豆瓣补全、批量操作、打开与下载
    shelves  书架列表、详情与增删改
    tools    统计仪表盘、批量导入、作者国籍、路径修正、恢复/导出、在线发布
    api      文件服务、原生对话框、元数据查询、封面上传
"""

from shelfmark.views import (api, books, browse, shelves, system, tools)

# 注册顺序：上下文注入最先（供所有页面使用），其余按领域注册。
# Flask 的注册顺序不影响路由匹配结果，端点名唯一即可。
MODULES = (system, browse, books, shelves, tools, api)


def register_all(app):
    """把所有视图模块注册到 Flask 应用（在 app.py 中创建 app 后调用一次）。"""
    for module in MODULES:
        module.register(app)


__all__ = ["register_all", "MODULES", "system", "browse", "books",
           "shelves", "tools", "api"]
