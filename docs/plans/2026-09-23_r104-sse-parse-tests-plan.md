# R104 批次计划 —— HttpClientMcpClient SSE 解析路径测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r104-sse-tests`（基于 origin/main adfa3e37）

## 背景

MCP Streamable-HTTP 协议允许服务器对同一 endpoint 回 JSON 或 SSE。
r102 只覆盖了 JSON 路径；`_parse_sse`（data: 行解析、按 JSON-RPC id 匹配、
错误行聚合）无测试。SSE 回复被静默解析错会导致工具结果丢失或错误吞没。

## 批次内容

新增 `backend/tests/unit/mcp/test_http_client_sse.py`（8 用例）：

纯函数面（`_parse_sse` 静态方法直调，6 用例）：
- 匹配 id 的 result 提取；
- 其他 id 的行忽略；
- 非 data 行（event:/注释/空行）与畸形 JSON 行跳过；
- 匹配 id 携带 error 且无 result → 抛 McpClientError（消息含 error 文本）；
- 多个匹配 id 的 error 行取最后一条；
- 全无匹配 id → 返回 None。

端到端（MockTransport 回 SSE content-type，2 用例）：
- `start()` + `list_tools()` 全链路走 SSE 响应；
- JSON 与 SSE 混合响应形态并存仍正确解析。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过。
- CI：Backend (Python) pytest 全量（MockTransport 纯内存）。

## 不做

- 不改生产代码。
