# MCP 工具禁用开关 UI（第五十三轮批次 A）实施计划

> 日期: 2026-09-18 · 分支: `feat/mcp-tool-toggle-r53` · 基于 main @ f528cbe7
> 来源: R20/#690 的收口项——后端 `disabled_tools` 已就绪但前端 McpTab
> 未暴露工具列表和禁用开关。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施

### A. 前端类型 + API（S）

- `McpServerStatusEntry` 增 `disabled_tools?: string[]`（后端
  `_config_to_dict` 已含此字段）
- `UpdateMcpServerChanges` 增 `disabledTools?: string[]`
- `mcpClient.updateServer()` 透传

### B. McpTab UI（M）

- 每个服务器卡片下方展开显示工具列表（从 status 接口获取
  `tool_specs`，映射 name + description）
- 每个工具旁 toggle switch 调 PATCH API
- disabled 工具显示灰色 + toggle off

### C. 后端（S）

- `GET /mcp/servers` 响应的每条 server 增加 `tool_names: string[]`
  （当前只有 tool_count），前端据此展示工具名列表

## 测试

- 后端: mcp_routes 工具名暴露测试
- 前端: McpTab 工具列表渲染 + toggle 调用链
- tsc / eslint 全绿

## 本批不做

- MCP OAuth 完整授权流 (L)
- stdio 传输 env 注入增强
