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

## Phase 3: LLM 驱动 Ingest (两步 CoT) ✅

### 目标

把 wiki ingest 从"占位 TODO"升级为"完整 LLM 集成",实现 6 步管线 + SHA256 增量缓存。

### 新增文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src-tauri/src/wiki/frontmatter.rs` | 解析/序列化 YAML frontmatter + extract_wikilinks | ~290 |
| `src-tauri/src/wiki/http.rs` | reqwest HTTP 客户端(post_json 通用方法) | ~110 |
| `src-tauri/src/wiki/ingest.rs` | **重写** 完整 6 步 ingest 管线 | ~450 |

### 修改文件

- `src-tauri/src/wiki/commands.rs`: `wiki_ingest_source` 签名扩展加 3 个 embedding 参数
- `src-tauri/src/wiki/mod.rs`: 导出 frontmatter + http
- `src/shared/api-client/wiki.ts`: `wikiIngestSource` 包装加 3 个 embedding 参数
- `src-tauri/Cargo.toml`: 新增 `sha2 = "0.10.9"`(SHA256 摘要)

### Ingest 6 步管线

```
1. 复制源 → raw/sources/{filename}
2. SHA256 摘要;命中 cache → 跳过 LLM,直接返回 cached=true
3. Step 1 LLM 分析 → entities/concepts/tags/related_topics/summary (JSON)
4. Step 2 LLM 写作 → 完整 wiki 页面 (markdown + frontmatter)
5. 解析 frontmatter (frontmatter::parse) + body
6. 写 wiki/sources/{slug}.md (原子写)
7. chunk_markdown + embed + VectorStore.upsert_chunks
8. 更新 ingest-cache.json
```

### 公共 API

```rust
// frontmatter
pub struct Frontmatter { title, page_type, tags, related, sources, created, updated, extra }
pub struct ParsedDoc { frontmatter, body }
pub fn parse(content: &str) -> ParsedDoc;
pub fn serialize(doc: &ParsedDoc) -> String;
pub fn extract_wikilinks(content: &str) -> Vec<String>;

// http
pub struct HttpClient { client: reqwest::Client, timeout: Duration }
impl HttpClient {
    pub fn new() -> Self;
    pub fn with_timeout(timeout: Duration) -> Self;
    pub async fn post_json(&self, url: &str, headers: &HashMap, body: &Value) -> Result<String, String>;
}

// ingest
pub struct IngestConfig { llm: LlmProviderConfig, embedding: EmbeddingConfig, max_content_chars: usize }
pub struct IngestOutcome { source_path, wiki_page_path, page_type, cached: bool }
pub async fn ingest_source(
    config: &IngestConfig,
    http: &HttpClient,
    project_root: &Path,
    source_file_path: &Path,
) -> Result<IngestOutcome, String>;
```

### LLM 推断策略

`commands.rs` 按 `api_url` 关键词推断 provider:
- 包含 `anthropic` → `Provider::Anthropic`
- 包含 `localhost:11434` → `Provider::Ollama`
- 其他 → `Provider::OpenAI`(默认)

未来 Phase 7 进度事件 + 流式 chat 时,前端会显式传 `provider` 字段,这里先按 URL 启发式。

### 关键设计

1. **两步 CoT** (分析 → 写作): 与 llm_wiki 一致,质量显著高于单次 LLM 调用
2. **宽松 JSON 解析** (`parse_analysis_json`): 提取首个 `{` 到最后 `}` 之间的内容,容忍 markdown fence + 前导文本
3. **SHA256 增量缓存**: 源文件未变更则跳过两次 LLM 调用,节省 token 成本
4. **原子写 wiki 页面**: 临时文件 + rename,避免半写状态
5. **slugify 中英兼容**: 中文字符保留,英文小写 + `-` 分隔
6. **HTTP 客户端 30 分钟 timeout**: 同 llm_wiki,长文档 LLM 处理可能慢

### 单元测试覆盖(34/34 通过)

**frontmatter** (18 测试):
- parse 无 frontmatter / 简单 / list / related / sources / dates / 未知字段
- serialize 往返 / 空 frontmatter
- extract_wikilinks 简单 / 多个 / alias / 去重 / 无 / 未闭合

**http** (4 测试):
- new 30min timeout / with_timeout / with_timeout(0) / default

**ingest** (12 测试):
- sha256 空串 / hello
- slugify 各种边界(中文/连续分隔符/特殊字符)
- parse_analysis_json 严格 JSON / markdown fence / 前导文本 / 无效
- cache 往返 / 缺失

### 累计 wiki 测试: 77 passed (Phase 1 20 + Phase 2 24 + Phase 3 33)

### 与后续 Phase 衔接

- **Phase 4 (RAG Chat)**: 调 `VectorStore::search` + token search 做 hybrid retrieval
- **Phase 5 (Graph)**: 调 `frontmatter::extract_wikilinks` 解析 `[[X]]` 链接
- **Phase 7 (UI)**: 进度事件 + 流式 chat(IngestOutcome 已有 `cached` 字段)

## Phase 4: RAG 增强 Wiki Chat ✅

### 目标

把 wiki chat 从"占位回答页面列表"升级为"完整 RAG 增强回答",实现 hybrid retrieval (token + 向量) + LLM 综合 + token 预算管理。

### 新增文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src-tauri/src/wiki/rrf.rs` | Reciprocal Rank Fusion 融合 (k=60) | ~110 |
| `src-tauri/src/wiki/context_budget.rs` | Token 预算分配 (50/30/5/15) + 截断 | ~170 |

### 修改文件

- `src-tauri/src/wiki/chat.rs`: **重写** RAG 完整管线 (~300 行)
- `src-tauri/src/wiki/commands.rs`: `wiki_chat` 签名扩展加 3 个 embedding 参数
- `src-tauri/src/wiki/mod.rs`: 导出 rrf + context_budget
- `src/widgets/wiki/WikiChat.tsx`: 加 3 个 embed 参数(复用 chat 端点作 embedding)
- `src/shared/api-client/wiki.ts`: `wikiChat` 包装加 3 个参数

### RAG 8 步管线

```
1. token search (search_wiki)  →  Vec<String> token_paths
2. embed query + 向量 search (VectorStore::search)  →  Vec<String> vector_paths
3. RRF 融合 (rrf_fuse)  →  Vec<(String, f64)> 按 RRF score 降序
4. 取 top_k fused  →  top_k 页面路径
5. 读 wiki 页面内容
6. token 预算 + truncate (ContextBudget + truncate_pages)
7. 拼装 RAG prompt (RAG_SYSTEM + 截断后 pages + query)
8. 调 LLM 综合回答
```

### 公共 API

```rust
// rrf
pub const DEFAULT_RRF_K: f64 = 60.0;
pub fn rrf_fuse<T: Hash + Eq + Clone>(token_hits: &[T], vector_hits: &[T], k: f64) -> Vec<(T, f64)>;

// context_budget
pub const PAGES_RATIO: f64 = 0.50;
pub const HISTORY_RATIO: f64 = 0.30;
pub const INDEX_RATIO: f64 = 0.05;
pub const RESERVE_RATIO: f64 = 0.15;
pub const DEFAULT_MAX_TOKENS: u32 = 8192;
pub struct ContextBudget { total, pages, history, index, response_reserve, per_page_cap }
pub struct PageChunk { page_path, content, truncated }
impl ContextBudget {
    pub fn compute(model_max_tokens: u32) -> Self;
    pub fn estimate_tokens(text: &str) -> u32;
}
pub fn truncate_pages(pages: &[(String, String)], budget: &ContextBudget) -> Vec<PageChunk>;

// chat (重写)
pub struct RagConfig { llm, embedding, max_tokens, retrieval_limit, final_top_k }
pub struct RetrievalStats { token_hits, vector_hits, fused_top_score, total_context_tokens }
pub struct WikiChatOutcome { answer, citations, stats }
pub async fn chat_with_wiki(config, http, project_root, query) -> Result<WikiChatOutcome, String>;
```

### 关键设计

1. **RRF (Reciprocal Rank Fusion) k=60**: 论文推荐值,平衡 token + 向量排名
2. **Token 预算 50/30/5/15**: 与 llm_wiki 一致,pages 50% / history+system 30% / index 5% / reserve 15%
3. **per_page_cap = total/8**: 防止一坨内容压垮 context
4. **极简 token 计数 (chars/3)**: MVP 简化,精度足够,可后续换 `tiktoken-rs`
5. **MVP embedding 复用 chat 端点**: Settings 暂未单独配 embedding,先用 chat 端点 + text-embedding-3-small
6. **融合降序 + 跳过空 hits**: 任意一边为空时另一边仍参与,空 result 直接返回 "未找到"

### 单元测试覆盖(18/18 通过)

**rrf** (7):
- 空输入 / 只 token / 只 vector / 交叉 boost score / dedup / 自定义 k / 不重叠

**context_budget** (8):
- compute 70% 上限 / caps at default / ratios sum / per_page cap / estimate_tokens
- truncate: within / huge / stops when exhausted

**chat** (3):
- RagConfig default / RetrievalStats default / PartialEq 行为

### 累计 wiki 测试: 95 passed (Phase 1 20 + Phase 2 24 + Phase 3 33 + Phase 4 18)

### 与后续 Phase 衔接

- **Phase 5 (Graph)**: 调 `frontmatter::extract_wikilinks` + 解析 `[[X]]` 链接
- **Phase 6 (Graph UI)**: 显示图谱
- **Phase 7 (进度 + 流式)**: `WikiChatOutcome.stats` 已可用于前端展示,流式拆分需 Phase 7 进一步

## Phase 5: 4-signal 知识图谱生成 ✅

### 目标

把 wiki 页面解析为节点 + 边,实现 4-signal 相关性评分(对齐 llm_wiki),支持 2-hop 扩散与缓存。

### 新增文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src-tauri/src/wiki/graph.rs` | 节点构建 + 4-signal 边 + relevance 2-hop + mtime 缓存 | ~580 |

### 修改文件

- `src-tauri/src/wiki/commands.rs`: 新增 `wiki_get_graph` Tauri 命令
- `src-tauri/src/wiki/models.rs`: re-export GraphData/GraphNode/GraphEdge
- `src-tauri/src/main.rs`: 注册 `wiki_get_graph` 命令
- `src-tauri/src/wiki/mod.rs`: 导出 graph
- `src/shared/types/wiki.ts`: 新增 `GraphSignal` / `GraphNode` / `GraphEdge` / `GraphData` 类型
- `src/shared/api-client/wiki.ts`: 新增 `getWikiGraph()` 包装
- `docs/technical/25-llm-wiki-integration.md`: 本章节

### 4-signal 边权重 (对齐 llm_wiki)

| Signal | 权重 | 计算方式 |
|---|---|---|
| **DirectLink** | ×3.0 | `[[wikilink]]` 出现一次 +3.0 |
| **SourceOverlap** | ×4.0 | `(shared_sources / max(\|a\|, \|b\|)) × 4.0` |
| **TypeAffinity** | ×1.0 | 两页同 `type` 字段 +1.0 |
| Adamic-Adar | TODO | 未来 Phase |

### wikilink 解析策略

`resolve_wikilink` 3 级 fallback:
1. 节点 `label` 精确匹配
2. 节点 `id` (file path) 精确匹配
3. label 模糊匹配(lower-case + slug 化,中文保留)

### 缓存机制

`compute_mtime_signature` 拼接所有 wiki/*.md 的 mtime + path → 字符串;与 `.llm-wiki/graph-cache.json` 的签名匹配则直接 load,否则 rebuild + save。原子写(临时 + rename)。

### 公共 API

```rust
pub enum SignalType { DirectLink, SourceOverlap, TypeAffinity }
impl SignalType { pub fn weight(self) -> f32 }
pub struct GraphNode { id, label, page_type, sources, wikilinks }
pub struct GraphEdge { source, target, signal, weight }
pub struct GraphData { nodes, edges }
pub fn build_graph(project_root: &Path) -> Result<GraphData, String>;
pub fn relevance(query: &str, graph: &GraphData, k_hops: u32) -> Vec<(String, f32)>;
pub fn relevance_with_decay(query, graph, k_hops, decay) -> Vec<(String, f32)>;
pub fn relevance_from_seeds(seed_ids, graph, k_hops) -> Vec<(String, f32)>;
pub fn get_graph_cached(project_root, query, limit) -> Result<GraphData, String>;
```

### Tauri 命令

```rust
#[command]
pub async fn wiki_get_graph(
    project_path: String,
    query: Option<String>,
    limit: Option<usize>,  // 默认 100
) -> Result<GraphData, String>;
```

### 关键设计

1. **跳过 index.md / log.md**: 元数据不作为图节点
2. **边去重**: `(source, target, signal)` 三元组去重
3. **2-hop 扩散**: `score = parent_score × edge_weight × decay(0.5)`
4. **query 过滤 + limit**: 默认 limit=100,但 relevance 截断时至少保留 50 个相关节点
5. **mtime 缓存**: 零散 IO 性能优化,wiki 变更才重建

### 单元测试覆盖(23/23 通过)

**graph 构建** (10):
- signal 权重匹配设计 / slug 化基本 + 中文
- 空 wiki 目录 / 单页 / DirectLink / SourceOverlap + disjoint / TypeAffinity
- 综合(3 种 signal 都生成) / 跳过 index.md+log.md

**wikilink 解析** (3):
- 按 label / 按 slug(case-insensitive) / 未知返回 None

**relevance 2-hop** (6):
- 无 seed 空 / 单 seed / 2-hop decay / 0-hop 仅 seed / relevance_from_seeds / 排序降序

### 累计 wiki 测试: 115 passed (Phase 1 20 + Phase 2 24 + Phase 3 33 + Phase 4 18 + Phase 5 23)

### 与后续 Phase 衔接

- **Phase 6 (Graph UI)**: 调 `getWikiGraph(project, query, limit)` 渲染 React Flow
- **Phase 7 (进度 + 流式 UI)**: Phase 5 提供 RAG 相关性辅助

## Phase 6: React Flow 知识图谱视图 ✅

### 目标

把 Phase 5 生成的 4-signal 图谱数据用 React Flow 渲染,支持节点 click、query 高亮、图例。

### 新增/修改文件

| 文件 | 职责 | 行数 |
|---|---|---|
| `src/widgets/wiki/WikiGraphView.tsx` (新) | React Flow 渲染 + 节点/边/图例 | ~250 |
| `src/widgets/wiki/index.ts` | 导出 `WikiGraphView` | +1 |
| `src/widgets/wiki/WikiToolbar.tsx` | 加 `graph` view + `Network` 图标 | +1 |
| `src/shared/types/wiki.ts` | `WikiView` 加 `'graph'` + Graph 类型 | +25 |
| `src/shared/api-client/wiki.ts` | `getWikiGraph()` 包装(已 Phase 5 加) | 0 |
| `src/entities/wiki/store.ts` | 加 `graphData` / `graphQuery` / `loadGraph()` / `setGraphQuery()` | +30 |
| `src/pages/Knowledge.tsx` | 加 `GraphPanel` 子组件 + `useEffect` 懒加载 | +50 |
| `package.json` + `package-lock.json` | 加 `@xyflow/react@^12.11.0` | +1 dep |

### 公共 API

```tsx
import { WikiGraphView } from '../widgets/wiki';

<WikiGraphView
  data={graphData}              // GraphData: { nodes, edges }
  query="albert"                // 可选:高亮匹配节点
  onNodeClick={(path) => ...}   // 可选:点击节点回调
/>
```

```ts
// store
useWikiStore.getState().loadGraph(query?: string);  // 加载或重新加载图谱
useWikiStore.getState().setGraphQuery(q: string);   // 设置 query
```

### 节点/边可视化

- **节点**: 自定义 React 组件 `WikiNode`,按 `page_type` 颜色编码
  - `source` = 蓝,`entity` = 紫,`concept` = 绿,`query` = 黄,`synthesis` = 红
  - hover 时显示 frontmatter 摘要(title + type + source count + wikilink count)
  - 不匹配 query 时 dim 到 70% opacity
- **边**: 按 `signal` 颜色 + `weight` 粗细
  - `DirectLink` = 蓝(animated),`SourceOverlap` = 紫,`TypeAffinity` = 灰
  - strokeWidth = max(1, weight / 2)
- **图例**: 右上角浮层,显示节点类型 + 边类型 + 匹配计数
- **MiniMap + Controls**: 内置缩放/平移控件

### 简化布局

按 `id` 哈希到固定网格位置:`x = (i % cols) * 220, y = floor(i / cols) * 120`,其中 `cols = ceil(sqrt(N))`。无 dagre/force-layout(后续 Phase 可加)。

### 关键设计

1. **懒加载**: `useEffect` 监听 `activeView === 'graph' && !graphData` 才调 `loadGraph`,避免切到 graph 视图前就拉数据
2. **query 防抖**: onChange 立即更新 local,onBlur 或 Enter 才提交 store + reload(避免每次按键都 reload)
3. **节点 click → 切到 browser view**: 复用现有 `openFile` 行为,无需新逻辑
4. **类型扩展**: `WikiView` 加 `'graph'`,`WikiView = 'browser' | 'search' | 'chat' | 'graph'`
5. **依赖管理**: `@xyflow/react@^12.11.0`(latest stable),自带 `dist/style.css` 样式

### 单元测试覆盖(7/7 通过)

`WikiGraphView helpers`:
- `colorByType` 默认 / 映射
- `buildGraph` 节点/边生成 / query 过滤 / 大小写不敏感 / id 匹配

### 累计测试

| 范围 | 数量 |
|---|---|
| Rust (cargo test --lib wiki) | 115 |
| Frontend (vitest) | 99 (其中 7 个新增 WikiGraphView) |
| **合计** | **214** |

### 与后续 Phase 衔接

- **Phase 7 (进度 + 流式 UI)**: ingest/chunk 进度事件 + chat 流式
- **Phase 8 (E2E + 用户手册)**: Playwright 测试 graph view

## Phase 7-8: 计划中

详见 [docs/plans/2026-06-12_llm-wiki-llm-integration.md](../plans/2026-06-12_llm-wiki-llm-integration.md)。

- **Phase 7**: 进度反馈 + 流式 chat UI
- **Phase 8**: 端到端测试 + 用户手册

---

_本文档随 Phase 实施滚动更新。_
