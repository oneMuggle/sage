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

## Phase 2: 向量存储 + Embedding 客户端 ✅

### 目标

提供 `VectorStore` 给后续 Phase 3 (Ingest) 和 Phase 4 (Chat) 调用,实现 wiki 的语义检索能力。

### 选型决策(重要)

**最初计划用 LanceDB,实测不兼容 sage Rust 1.77.2 / edition2021**:
- lancedb 0.10-0.30 全部拉 lance 0.10-0.20,lance 内部 async block 类型 layout 深度 > 128
- 触发 Rust 1.77 `queries overflow the depth limit` 错误
- Workaround (`-Z crate-attr=recursion_limit=512`) 需要 nightly Rust,sage 锁 stable

**备选 sqlite-vec (0.1.10-alpha.4) 也有自身 bug**:打包漏 `sqlite-vec-diskann.c`

**最终选定: 纯 Rust 自实现,零新依赖**:
- `Vec<f32>` 存向量,JSON 文件持久化
- Brute-force cosine similarity + top-k
- 规模上限 < 1万 chunk(MVP wiki 规模足够)
- 后续如需扩展到 10万+ chunk,可平滑切换 HNSW (如 `usearch`)

### 新增文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src-tauri/src/wiki/embeddings.rs` | chunk_markdown + OpenAI 兼容 /v1/embeddings 客户端 | ~270 |
| `src-tauri/src/wiki/vectorstore.rs` | 嵌入式 JSON 向量存储 + cosine 检索 | ~340 |

### 公共 API

```rust
// embeddings
pub struct EmbeddingConfig { base_url, api_key, model, dim }
pub struct EmbedHttpRequest { url, method, headers, body }
pub const DEFAULT_CHUNK_SIZE: usize = 500;
pub const DEFAULT_CHUNK_OVERLAP: usize = 50;
pub fn chunk_markdown(content: &str, target: usize) -> Vec<String>;
pub fn build_embed_request(config: &EmbeddingConfig, texts: &[String]) -> EmbedHttpRequest;
pub fn parse_embed_response(body: &str, expected_dim: u32) -> Result<Vec<Vec<f32>>, String>;

// vectorstore
pub struct ChunkRecord { id, page_path, chunk_index, content, vector }
pub struct SearchHit { page_path, chunk_index, content, score }
pub struct VectorStore { ... }  // 不导出字段
impl VectorStore {
    pub fn open(project_root: &Path, dim: u32) -> Result<Self, String>;
    pub fn upsert_chunks(&mut self, page_path: &str, chunks: &[(u32, String, Vec<f32>)]) -> Result<(), String>;
    pub fn delete_by_page(&mut self, page_path: &str) -> usize;
    pub fn search(&self, query_vec: &[f32], limit: usize) -> Result<Vec<SearchHit>, String>;
    pub fn len(&self) -> usize;
    pub fn is_empty(&self) -> bool;
}
```

### chunk_markdown 切分策略

1. 按 `\n\n`(空行)切成段落
2. 合并过短段落(累加直到接近 `target_chunk_size`)
3. 切分过长段落(强制 `target_chunk_size`,带 50 字符 overlap)

### VectorStore 文件格式

`{project_root}/.llm-wiki/vectors.json`:

```json
{
  "version": 1,
  "dim": 1536,
  "records": [
    {
      "id": "wiki/sources/albert-einstein.md::0",
      "page_path": "wiki/sources/albert-einstein.md",
      "chunk_index": 0,
      "content": "1879-1955,德国物理学家...",
      "vector": [0.012, -0.034, ...]
    }
  ]
}
```

- 原子写(临时文件 + rename)
- 维度不匹配时 `open` 失败(防止 embedding 模型切换后检索错误)
- 全量内存索引(适合 < 1万 chunk;超过需要 HNSW)

### 单元测试覆盖(24/24 通过)

```
test wiki::embeddings::tests::chunk_empty_returns_empty ... ok
test wiki::embeddings::tests::chunk_huge_paragraph_gets_split_with_overlap ... ok
test wiki::embeddings::tests::chunk_long_content_splits_into_multiple ... ok
test wiki::embeddings::tests::chunk_preserves_markdown_structure ... ok
test wiki::embeddings::tests::chunk_short_paragraphs_merged ... ok
test wiki::embeddings::tests::chunk_single_paragraph_returns_one ... ok
test wiki::embeddings::tests::embed_request_batch_input ... ok
test wiki::embeddings::tests::embed_request_omits_auth_when_no_key ... ok
test wiki::embeddings::tests::embed_request_url_and_auth ... ok
test wiki::embeddings::tests::parse_response_extracts_vectors ... ok
test wiki::embeddings::tests::parse_response_invalid_json_errors ... ok
test wiki::embeddings::tests::parse_response_missing_data_errors ... ok
test wiki::embeddings::tests::parse_response_with_no_dim_check ... ok
test wiki::embeddings::tests::parse_response_wrong_dim_errors ... ok
test wiki::vectorstore::tests::delete_by_page_removes_all_chunks_of_page ... ok
test wiki::vectorstore::tests::open_empty_when_file_missing ... ok
test wiki::vectorstore::tests::open_persists_and_reloads ... ok
test wiki::vectorstore::tests::open_with_mismatched_dim_errors ... ok
test wiki::vectorstore::tests::search_after_delete_omits_removed_page ... ok
test wiki::vectorstore::tests::search_returns_top_k_by_cosine ... ok
test wiki::vectorstore::tests::search_with_wrong_dim_errors ... ok
test wiki::vectorstore::tests::search_with_zero_query_vector_returns_empty ... ok
test wiki::vectorstore::tests::upsert_replaces_existing_page_chunks ... ok
test wiki::vectorstore::tests::upsert_with_wrong_dim_errors ... ok
```

### 关键设计决策

1. **零新依赖**: 整个 Phase 2 不加任何 Cargo.toml 依赖(只复用现有 serde + serde_json + std)
2. **build_request 模式**: 同 llm_provider,实际 HTTP 调用推迟到 Phase 4,单元测试不需 mock
3. **维度硬约束 1536**: 与 text-embedding-3-small 绑定;切换模型需清空 vectors.json
4. **文件路径 `.llm-wiki/`**: 与 llm_wiki 一致(便于将来迁移),不进 git
5. **MVP 规模假设**: < 1万 chunk 性能足够(每搜索 1ms 内),超过时切换 HNSW

### 与后续 Phase 的衔接

- **Phase 3 (Ingest)**: 调 `chunk_markdown` + `build_embed_request` + `VectorStore::upsert_chunks`
- **Phase 4 (RAG Chat)**: 调 `build_embed_request` + `VectorStore::search` 做 hybrid retrieval
- **Phase 5-7**: 暂不直接调用

## Phase 3-8: 计划中

详见 [docs/plans/2026-06-12_llm-wiki-llm-integration.md](../plans/2026-06-12_llm-wiki-llm-integration.md)。

- **Phase 3**: LLM 驱动 Ingest(两步 CoT 分析→写作)+ frontmatter 解析 + wikilink 提取
- **Phase 4**: RAG 增强 Wiki Chat(token + 向量 RRF + token 预算)
- **Phase 5**: 4-signal 知识图谱生成
- **Phase 6**: React Flow 知识图谱视图
- **Phase 7**: 进度反馈 + 流式 chat UI
- **Phase 8**: 端到端测试 + 用户手册

---

_本文档随 Phase 实施滚动更新。_
