# r53-B 批次计划：MCP 工具禁用开关 —— 设置面板 UI + 工具清单 API

日期：2026-09-16（分支创建于 main@f528cbe7）
依赖：r53-A（PR #937，mcpClient/IPC 的 disabled_tools 数据链路）——本分支包含
等价改动行，rebase 时与 #937 去重；若 #937 先合并则 rebase 后仅剩本批次增量。

## 背景

R20/#690 已交付后端 per-tool 禁用能力（`ServerConfig.disabled_tools` +
`pool.update_server` + `PATCH /mcp/servers/{name}`），但：
1. 前端没有任何入口能看到/修改 disabled_tools（r53-A 打通数据链路）；
2. 后端没有"某服务器发现了哪些工具"的读取端点（status 只有 tool_count），
   UI 想渲染 per-tool 开关也无数据源。

## 交付内容

### 后端（1 个只读端点）
- `GET /api/v1/mcp/servers/{name}/tools`（mcp_routes.py）：
  - 从 pool 取 record（未知 → 404）；返回
    `{server, state, tools:[{name, description}], disabled_tools}`；
  - description 截断 200 字符；仅暴露 name+description（不透传 inputSchema）；
  - 只读，不触发 discovery（服务器未就绪 → tools 为空列表）。
- 测试：backend/tests/api/test_mcp_routes.py 增 TestServerTools
  （正常列出 / 404 / disabled_tools 回显）。

### 前端
- `mcpClient.ts`：`McpToolSpec`/`McpServerToolsReport` 类型 +
  `serverTools(name)`；`McpServerConfig.disabled_tools`；
  `UpdateMcpServerChanges.disabledTools`（与 r53-A 同内容，rebase 去重）。
- `electron/commands.ts`：`mcp_server_tools` 路由；`mcp_server_update`
  body 增 disabled_tools（同上）。
- `McpTab.tsx`：每行增"工具"展开按钮 → 懒加载工具清单 → 每个工具一个
  勾选框（勾选=启用；取消勾选=加入 disabled_tools，全量替换 PATCH），
  展开时重新拉取保证最新；加载失败/空列表内联提示。
- i18n：zh.ts/en.ts 增 settings.mcp.tools.* 键。

### 测试
- commands.test.ts：新路由断言。
- McpTab.test.tsx：展开 → serverTools 调用 → 取消勾选 →
  updateServer(name, {disabledTools: 全量列表})。

## 不做
- 不改 pool/注册语义（R20 已测）；
- 不做工具级搜索/批量操作（后续按需）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
