# r54 批次计划：非 openai provider 流式对话测试补齐

日期：2026-09-16（分支创建于 main@2a37bb5c）
无文件冲突面：纯新增测试文件（与 #943 MCP 批次零交集）。

## 背景

LLMClient（backend/core/legacy/llm_client.py）是 openai 兼容协议的统一客户端，
provider（claude/gemini/deepseek/ollama/custom）只影响 body 细节与端点。现有流式
测试覆盖：
- test_llm_client_stream_errors.py：错误分类（mock，openai）；
- test_llm_stream_tool_calling.py：chat_stream_events 事件协议（provider 固定 openai）；
- test_llm_client_reasoning_params.py：唯一一个非 openai 流式用例
  （deepseek + reasoning_effort）。

即：claude / gemini / ollama 三个真实 provider 的流式对话没有任何端到端
（respx SSE 回环）覆盖——回归（如 body 组装改动、SSE 解析改动）只能靠 CI 偶然
兜底。本批次补齐。

## 交付内容（纯测试，零产品代码改动）

新文件 `backend/tests/unit/test_llm_stream_providers.py`（respx SSE mock，
pytestmark=unit，直连模式 use_proxy=False）：

1. claude `chat_stream` 回环：chunks 顺序透传、body 含 `max_tokens`（claude
   硬性要求）+ `stream=True`、无 reasoning 键（未配置时不注入）；
2. claude `chat_stream_events` 回环：事件序列 content_delta* → response，
   终值 content 等于增量拼接、body 含 `stream_options.include_usage`；
3. gemini `chat_stream` 回环（OpenAI 兼容端点）：`thinking_budget` 透传进
   流式 body，chunks 透传；
4. ollama `chat_stream` 回环：空 api_key 不产生 `Authorization` 头
   （本地无鉴权上游），`[DONE]` 正常终止；
5. ollama `chat_stream_events` 推理增量：`delta.reasoning_content` →
   `reasoning_delta` 事件，content 增量互不污染（reasoning 模型回环）。

## 不做
- 不改产品代码；若测试暴露真实 bug，另开修复批次；
- 不测 proxy 路径（已有 test_llm_proxy_routes / test_llm_proxy_url 覆盖）。

## Win7 对齐
纯测试新增，主分支 CI 资产；不涉及产品行为，无需回流 win7
（win7 分支的测试基线由其自身策略管理）。
