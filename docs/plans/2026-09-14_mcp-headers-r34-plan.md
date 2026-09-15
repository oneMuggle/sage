# MCP HTTP 鉴权头（第三十四轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/mcp-headers-r34` · 基于 main @ 7310444e
> 来源: 第二十一轮差距分析 #6 残项——"HTTP server 仅裸 url+env，无
> OAuth/授权头配置"。本批补鉴权头部分（完整 OAuth dance 为 L 级另批）。
> 与并发车道零交集。Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景（证据）

- 远端 MCP 服务器普遍要求 `Authorization: Bearer <PAT>`；MCP HTTP
  客户端（http_client.py `_post`）只发 Accept/Content-Type/
  Mcp-Session-Id，`ServerConfig` 仅有 env（stdio 用）——HTTP 传输用户
  无法携带鉴权头接入带 PAT 的远端服务器。

## 实施

### A. ServerConfig.headers（S）

- `headers: Dict[str, str]` 字段（仅 HTTP 传输消费；stdio 客户端
  忽略）+ `to_dict` 序列化 + `validate_server_config` 校验（键非空
  字符串、值必须字符串）+ `_config_from_dict` 解析。

### B. 客户端合并（S）

- `HttpClientMcpClient._post`: 每次请求合并 `config.headers`（不覆盖
  传输必需的 Accept/Content-Type/Mcp-Session-Id 会话头——会话头后置
  且自定义头先合并，会话头优先级更高）。

### C. 配置链路 + API（S）

- `pool.update_server(headers=...)`: 全量替换语义；READY 服务器
  变更触发既有 re-discovery（客户端构造时烘焙 headers）。
- `ServerConfigIn.headers` / `ServerUpdateIn.headers` + 两个路由透传。
- GET 脱敏: `_config_to_dict` 对 headers 应用与 env 相同的
  `redact_env` 敏感键脱敏（authorization/token/key/…）——绝不回显
  PAT 到渲染层。

## 测试

- `test_mcp_auth_headers`: config round-trip + 非法键/值拒绝；
  MockTransport 断言每次 JSON-RPC 请求（initialize 与后续 tools/list）
  都携带自定义头、会话头不被自定义头覆盖。
- 既有 mcp 套件回归。

## 本批不做（后续候选）

- 完整 OAuth dance（授权码流 + token 刷新，L）
- stdio 传输的 env 注入增强（env 字段已覆盖）
- per-header 敏感度标注（沿用 env 同款标记脱敏已够）
