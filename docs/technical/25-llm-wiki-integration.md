# 25. LLM Wiki 集成(PR-8)

> 状态: Phase 1 ✅ · Phase 2-8 计划中
> 前置: [docs/plans/2026-05-30_llm-wiki.md](../plans/2026-05-30_llm-wiki.md)(Phase 1-5)
> 计划: [docs/plans/2026-06-12_llm-wiki-llm-integration.md](../plans/2026-06-12_llm-wiki-llm-integration.md)
> 参考实现: `/home/fz/project/llm_wiki`

本文档分 8 个 phase 介绍 sage 的 LLM Wiki 集成(借鉴 Karpathy "LLM 驱动个人知识库"模式 + llm_wiki 的 Rust 桌面实现)。当前 Phase 1 已完成。

## Phase 1: LLM Provider 抽象层 ✅

### 目标

让 wiki 的 `ingest` 与 `chat` 都能用一套公共接口调用 4 个 LLM provider,不耦合具体协议。

### 新增文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src-tauri/src/wiki/llm_provider.rs` | 公共类型 + 4 provider 实现 + 单元测试 | ~430 |
| `src-tauri/src/wiki/llm_prompts.rs` | 4 个 prompt 模板常量 + format 便利函数 + 单元测试 | ~150 |

### 公共 API

```rust
// 公共类型
pub enum Provider { OpenAI, Anthropic, Ollama, Custom }
pub struct LlmProviderConfig { provider, base_url, api_key, model, max_tokens, temperature, custom_headers }
pub struct ChatMessage { role, content }
pub struct ChatRequest { messages, max_tokens, temperature }
pub struct ChatResponse { content, prompt_tokens, completion_tokens }
pub struct HttpRequest { url, method, headers, body: serde_json::Value }

// 公共入口(按 Provider 分发)
pub fn build_request(config: &LlmProviderConfig, request: &ChatRequest) -> Result<HttpRequest, String>;
pub fn parse_response(provider: &Provider, body: &str) -> Result<ChatResponse, String>;
```

### 4 个 provider 的协议差异

| 维度 | OpenAI | Anthropic | Ollama | Custom |
|---|---|---|---|---|
| **endpoint** | `POST {base}/chat/completions` | `POST {base}/v1/messages` | `POST {base}/chat/completions` | `POST {base}/chat/completions` |
| **鉴权头** | `Authorization: Bearer {key}` | `x-api-key: {key}` + `anthropic-version: 2023-06-01` | 无 | `Authorization: Bearer {key}` + 自定义头 |
| **system 消息** | 放在 `messages[0]` | 抽到顶层 `system` 字段 | 放在 `messages[0]` | 放在 `messages[0]` |
| **响应 content 路径** | `choices[0].message.content` | `content[0].text` | (OpenAI 兼容) | (OpenAI 兼容) |
| **token 字段** | `usage.prompt_tokens` / `completion_tokens` | `usage.input_tokens` / `output_tokens` | (OpenAI 兼容) | (OpenAI 兼容) |
| **api_key 必填** | 否 | **是** | 否 | 否 |

### Prompt 模板

`llm_prompts.rs` 集中 4 个模板,Phase 3/4 会用到:

| 常量 | 用途 | 占位符 |
|---|---|---|
| `STEP1_ANALYZE` | Step 1: 提取实体/概念/标签/相关主题 | `{source_content}` |
| `STEP2_WRITE` | Step 2: 写完整 wiki 页面(frontmatter + body) | `{filename}` `{content}` `{analysis}` `{tags_csv}` `{related_links}` `{today}` |
| `RAG_SYSTEM` | wiki_chat 系统提示词(强调不引入外部知识) | 无 |
| `RAG_USER_TEMPLATE` | wiki_chat 用户消息模板 | `{query}` |

### 单元测试覆盖(20/20 通过)

```
running 20 tests
test wiki::llm_prompts::tests::rag_system_emphasizes_no_external_knowledge ... ok
test wiki::llm_prompts::tests::rag_user_message_includes_query ... ok
test wiki::llm_prompts::tests::step1_prompt_includes_source_content ... ok
test wiki::llm_prompts::tests::step2_prompt_replaces_all_placeholders ... ok
test wiki::llm_prompts::tests::step2_prompt_contains_frontmatter_template ... ok
test wiki::llm_provider::tests::anthropic_build_request_extracts_system_to_top_level ... ok
test wiki::llm_provider::tests::anthropic_build_request_requires_api_key ... ok
test wiki::llm_provider::tests::anthropic_build_request_url_is_v1_messages ... ok
test wiki::llm_provider::tests::anthropic_build_request_uses_x_api_key_and_anthropic_version ... ok
test wiki::llm_provider::tests::anthropic_parse_response_extracts_content_and_input_output_tokens ... ok
test wiki::llm_provider::tests::build_request_dispatches_by_provider ... ok
test wiki::llm_provider::tests::custom_build_request_passes_through_custom_headers ... ok
test wiki::llm_provider::tests::custom_parse_response_uses_openai_compatible_format ... ok
test wiki::llm_provider::tests::ollama_build_request_url_uses_default_base ... ok
test wiki::llm_provider::tests::ollama_parse_response_uses_openai_compatible_format ... ok
test wiki::llm_provider::tests::openai_build_request_body_has_model_messages_max_tokens ... ok
test wiki::llm_provider::tests::openai_build_request_includes_bearer_auth ... ok
test wiki::llm_provider::tests::openai_build_request_url_is_chat_completions ... ok
test wiki::llm_provider::tests::openai_parse_response_missing_choices_returns_err ... ok
test wiki::llm_provider::tests::openai_parse_response_extracts_content_and_usage ... ok

test result: ok. 20 passed; 0 failed
```

### 关键设计决策

1. **不动 reqwest,只构造请求**: `HttpRequest { url, method, headers, body }` 是纯数据结构,实际 HTTP 调用由 Phase 3/4 写。这样:
   - 单元测试不需要 mock HTTP
   - 多 provider 的协议差异集中在 `build_request` / `parse_response`
   - 易于扩展(加 Claude-CLI/Codex-CLI 时只需新增 provider)

2. **Anthropic 特殊处理 system 消息**: Anthropic API 要求 `system` 字段独立到顶层,不能放 `messages[]`。`build_anthropic_request` 自动转换。

3. **Ollama 走 OpenAI 兼容协议**: Ollama 1.0+ 提供 `/v1/chat/completions` 端点,响应格式与 OpenAI 一致,直接复用 `parse_openai_response`。

4. **Custom 与 OpenAI 协议同源**: Custom 用于代理/中转(如 Azure、自部署 OpenAI 兼容服务),总是带 Authorization + 允许自定义头覆盖。

5. **Prompt 字符串集中**: 4 个 prompt 模板在 `llm_prompts.rs` 用 `pub const &str`,`format_*` 函数显式声明占位符,避免 `format!` 漏传/拼写错。

### Phase 1 验收 ✅

- [x] 4 个 provider 的 build_request 单元测试全绿
- [x] 4 个 provider 的 parse_response 单元测试全绿
- [x] 4 个 prompt 模板的 format 行为测试全绿
- [x] Anthropic 协议差异(headers + system 字段)正确处理
- [x] `cargo test --lib llm_` 20/20 通过
- [x] 无 `unwrap()` / `eprintln!` / 硬编码秘密
- [x] 公共 API 文档化(模块顶部注释)

### 与后续 Phase 的衔接

- **Phase 2 (VectorStore)**: 独立模块,等 LanceDB 选型确认
- **Phase 3 (Ingest 集成)**: 调用 `format_step1_prompt` + `format_step2_prompt` + `build_request` + `parse_response`
- **Phase 4 (RAG Chat)**: 调用 `RAG_SYSTEM` + `format_rag_user_message` + `build_request` + `parse_response`
- **Phase 5-7**: 暂不直接调用本模块,只通过 wiki 现有命令

## Phase 2-8: 计划中

详见 [docs/plans/2026-06-12_llm-wiki-llm-integration.md](../plans/2026-06-12_llm-wiki-llm-integration.md)。

- **Phase 2**: LanceDB 嵌入式向量存储 + OpenAI 兼容 embedding 客户端
- **Phase 3**: LLM 驱动 Ingest(两步 CoT 分析→写作)+ frontmatter 解析 + wikilink 提取
- **Phase 4**: RAG 增强 Wiki Chat(token + 向量 RRF + token 预算)
- **Phase 5**: 4-signal 知识图谱生成
- **Phase 6**: React Flow 知识图谱视图
- **Phase 7**: 进度反馈 + 流式 chat UI
- **Phase 8**: 端到端测试 + 用户手册

---

_本文档随 Phase 实施滚动更新。_
