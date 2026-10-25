# R107 批次计划 —— Wiki MCP server handler 面单测试

日期：2026-09-23 ｜ worktree：`.worktrees/fix-r107-projection-flake`（基于 origin/main 57b2e19a）

## 背景

`backend/wiki/mcp_server.py`（613 行，7 个 MCP 工具）目前仅有安全路径回归
（`test_wiki_mcp_security.py`：路径逃逸/符号链接拒绝）。该模块是
"可选导入 + 恒等装饰器直测"模式的原型（Zotero MCP server r95 批次即参照
它），正常返回面无测试。

> 备注：本 worktree 分支名沿用 fix/r107-projection-flake，但 event_projection
> 的间歇失败经核实属 #1421（另一会话）活跃迭代区且其作者已在自稳（-10s
> 基线注释），本批避让不改，转做 wiki handler 面。

## 批次内容

新增 `backend/tests/unit/mcp/test_wiki_mcp_handlers.py`（10 用例）：

- `list_tools`：7 工具名序锁定 + inputSchema 形状；
- `call_tool` 分发：status（页面数/图谱键）、files（根列表 + 子目录 +
  posix path 规范）、search（信封键与结果字段结构）、read（path/content
  精确断言）、graph（nodes/edges 结构）、communities/insights（JSON 对象）；
- 未知工具返回 `未知工具: <name>`；
- 缺必选参数（KeyError）落统一错误文案 `错误: Wiki 工具执行失败`。

环境：tmp 项目两页互链 wiki + `SAGE_MCP_WIKI_PROJECT_ROOTS` 授权；
Windows 跳过（handlers 依赖 `_require_posix_safety`，与安全回归同口径），
CI Linux 全量执行。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过（PT018 已拆分）。
- CI：Backend (Python) pytest 全量。

## 不做

- 不改生产代码；不碰 event_projection（避让 #1421 活跃区）。
