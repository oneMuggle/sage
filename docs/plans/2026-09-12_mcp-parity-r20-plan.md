# MCP 生态补强（第二十轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/mcp-parity-r20` · 基于 main @ 38576040
> 来源: 第十七轮差距分析后端报告 #6（MCP 是差距最小但仍有两块短板）。
> 与并发批次（gateway-configurable / memory-consolidation / excel）零交集。
> Win7 对齐: 能力补齐属功能增强，不 cherry-pick 到 release/win7。

## 背景（分析结论 + 代码证据）

- **stdio 传输不支持 resources/prompts**: `backend/mcp/http_client.py`
  已实现 `list_resources/read_resource/list_prompts/get_prompt`（L10），
  且 `pool.synthesize_extra_specs` 按 duck-typing 合成工具——但 stdio
  客户端（`backend/mcp/client.py`）缺这四个方法，stdio 服务器（多数
  npx/uvx 生态服务器）永远合成不出资源/prompt 工具。
- **无 per-tool 级开关**: `ServerConfig` 只有服务器级 `enabled`
  （`mcp_routes.py:68-76` ServerUpdateIn 仅 enabled/timeout_seconds）。
  某个服务器 30 个工具里只想暴露 2 个时无从下手。

## 批次任务

### A. stdio resources/prompts 补齐（S）

`backend/mcp/client.py` McpClient 增加四个方法，全部走既有
`_send_request` JSON-RPC 通道：`resources/list`、`resources/read`、
`prompts/list`、`prompts/get`。pool 侧零改动（duck-typing 自动生效）。

### B. per-tool 级开关（S）

- `ServerConfig.disabled_tools: Tuple[str, ...] = ()`（frozen dataclass
  归一化 + `to_dict` 序列化 + `validate_server_config` 参数校验 +
  `_config_from_dict` 解析）。
- 过滤点: `pool.register_tools_into` 与 `_register_server_tools` ——
  spec 原始名或 namespaced 名命中 `disabled_tools` 即跳过注册。
- `pool.update_server(..., disabled_tools=None)`: merge-patch；变更且
  READY 时走既有 re-discovery 路径刷新注册。
- `ServerUpdateIn.disabled_tools: Optional[List[str]]` + PATCH 透传。

## 测试

- stdio 客户端四方法请求路由（monkeypatch `_send_request`）。
- `synthesize_extra_specs` 对带 resources/prompts 的 stdio fake 客户端
  合成成功。
- `disabled_tools` 过滤（原始名 + namespaced 名两口径）。
- config 序列化 round-trip；`update_server` patch 与 re-discovery 触发。
- ruff 全绿。

## 本批不做（后续候选）

- MCP 配置 OAuth/鉴权头（M）
- npx/uvx 运行时自动探测（M）
- 管理面 per-tool 开关 UI（并发车道，避免冲突）
