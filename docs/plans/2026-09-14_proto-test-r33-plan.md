# 协议级连接测试（第三十三轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/proto-test-r33` · 基于 main @ be7c5e6a
> 来源: R26 (#713) 首启向导的遗留项——向导此前对非 openai 协议跳过
> 测试（"该协议请直接保存"），EndpointsTab 对所有协议都跑 openai 语义
> 的 /models + chat/completions（anthropic/gemini/ollama 必然假失败）。
> 与并发车道零交集。Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施（前端 only，复用既有 LLM 代理）

- `fetchModelsByProtocol(protocol, baseUrl, apiKey)`（新，经既有
  `/api/v1/llm/{path}` 透传代理——`_filter_request_headers` 原样转发
  自定义鉴权头）:
  - anthropic: GET `/v1/models` + `x-api-key` + `anthropic-version:
    2023-06-01` → `data[].id`
  - gemini: GET `/v1beta/models` + `x-goog-api-key` →
    `models[].name`（剥离 `models/` 前缀）
  - ollama: GET `/api/tags`（无鉴权头）→ `models[].name`
  - openai-compatible: 原路径
- `testEndpointConnection` 增加第 4 参 `protocol`（默认
  openai-compatible 向后兼容）：非 openai 协议只做模型发现，成功
  消息注明"该协议未做对话连通测试"（各家对话端点语义不同，不硬套）。
- `OnboardingWizard`: 全协议走测试步（移除非 openai 的"直接保存"
  分支与 skip_test_hint 文案用途），测试时透传 protocol。
- `EndpointsTab`: 测试透传 `ep.protocol`。

## 测试

- `api.test.ts` 新增 4 例: anthropic 头与解析 / gemini 头 + 前缀剥离 /
  ollama 无鉴权 / 非 openai 只做发现不做对话测试。
- 向导测试更新为协议参数透传断言；chat/onboarding 套件 30 例全过。
- tsc / eslint 全绿。

## 本批不做（后续候选）

- anthropic/gemini/ollama 的对话级连通测试（各家生成端点语义不同，
  需按协议构造最小 completion，M）
- gemini/ollama 协议的 chat 能力探测
