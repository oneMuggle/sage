# R95 批次计划 —— Zotero MCP server 测试收口

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r95-mcp-zotero-tests`（基于 origin/main 0ffbe01c）

## 背景

r94 修复了 Zotero REST 路由与设置持久化断链。#1367 的另一面 ——
`backend/mcp/servers/zotero/server.py`（430 行，7 个 MCP 工具）仍无测试。
该模块采用可选导入模式（`mcp` 包在 requirements-optional.txt，CI conda 环境
不安装）→ 装饰器为恒等，`call_tool`/`list_tools` 可作为普通异步函数直测。

## 批次内容

新增 `backend/tests/unit/test_zotero_mcp_server.py`（12 用例）：

- `list_tools()` 暴露 7 个工具，名称与顺序锁定，均带 object inputSchema；
- `call_tool` 分发：status（健康 ok → health+stats 双信封 / 不健康 → 仅
  health）、search（参数透传 + {query,total,results} 信封）、get_item
  （原样 item JSON）、annotations（{item_key,total,annotations}）、
  collections（parent_key 透传/缺省 None）、bibtex（非 JSON 原文）、
  read_pdf（chunk_offset/chunk_size/max_chars 默认值与覆盖）；
- 必选参数缺失（KeyError）落入统一错误信封
  `Error: Zotero tool '<name>' failed: ...`；
- 未知工具返回 `Unknown Zotero tool: <name>`。

fake client 注入模块单例 `_client`（monkeypatch），零真实 SQLite 依赖。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4（PT023 已按括号风格修正）。
- CI：Backend (Python) pytest 全量；架构门（基线 r94 已重算，本批新增
  文件 <800 行不触发）。

## 不做

- 不改生产代码。
- ZoteroTab UI 测试、orchEventStream 测试留待后续批次。
