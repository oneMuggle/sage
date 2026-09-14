# 非 openai 对话级连通测试（第三十六轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/proto-chat-test-r36` · 基于 main
> 来源: R33 (#757) 的收口项——非 openai 协议此前只做模型发现，
> 成功消息注明"该协议未做对话连通测试"。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施（前端 only，零后端变更，复用 LLM 代理透传）

`testChatCompletionByProtocol`（新，按协议构造最小 completion，全部经
`/api/v1/llm/{path}` 透传 + 协议鉴权头）：

- **anthropic**: POST `/v1/messages`（x-api-key + anthropic-version），
  body `{model, max_tokens: 16, messages:[{role:'user',content:'ping'}]}`
  → `content[0].text`
- **gemini**: POST `/v1beta/models/{model}:generateContent`
  （x-goog-api-key），body `{contents:[{parts:[{text:'ping'}]}],
  generationConfig:{maxOutputTokens:16}}` → `candidates[0].content.parts[0].text`
- **ollama**: POST `/api/chat`（无鉴权），body `{model, messages,
  stream:false}` → `message.content`

`testEndpointConnection` 非 openai 分支: 从"只做发现"升级为——选定
测试模型（优先传入 chatModel，否则第一个非 embedding），跑协议级
对话测试；成功消息 `连接成功 · 发现 N 个模型 · 对话连通 · model`；
失败沿用 `_parseUpstreamError` 中文翻译。无可用 chat 模型时降级为
仅发现成功。

## 测试

- `api.test` R33 用例更新为 R36 契约（ollama 断言 /api/chat body 与
  对话连通消息）。
- 既有 manage-endpoints + onboarding 套件 32 例全过；tsc/eslint 全绿。

## 本批不做

- anthropic/gemini/ollama 的流式对话测试（非流式 ping 已足够判定连通）
- 向导内的计费/余额查询
