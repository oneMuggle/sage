# LLM Wiki 完整化实施计划(借鉴 llm_wiki)

> **日期**: 2026-06-12
> **状态**: 计划中
> **参考项目**: `/home/fz/project/llm_wiki` (Karpathy "LLM 驱动个人知识库"模式 + Rust 桌面实现)
> **前置计划**: `docs/plans/2026-05-30_llm-wiki.md`(Phase 1-5 ✅ Rust 文件操作 + UI + 搜索)

## 背景与目标

### 现状

`docs/plans/2026-05-30_llm-wiki.md` 完成了 wiki 的**骨架**:

- ✅ Rust 侧: 9 个 Tauri 命令(项目 CRUD、文件 CRUD、搜索)
- ✅ 前端: 7 个 React 组件(FileTree / Editor / Preview / Search / Chat / Toolbar / ProjectPicker)
- ✅ CJK 全文搜索(已带 BM25-like 评分)
- ✅ `index.md` / `log.md` 自动维护
- ❌ **LLM 集成是 TODO** — `ingest.rs` 与 `chat.rs` 都有未实现的 LLM 调用位
- ❌ **无 embedding / 向量检索**
- ❌ **无知识图谱视图**

### 目标

借鉴 llm_wiki 的核心设计,把 sage 的 wiki 从"静态 markdown 仓库"升级为"**LLM 增量维护的知识库**":

1. **LLM 驱动的 ingest**: 导入源文档 → LLM 两步分析+生成 → 写入结构化页面
2. **RAG 增强的 chat**: token 搜索 + 向量检索 + LLM 综合回答(带引用)
3. **embedding + 向量存储**: 接入 `LanceDB`(与 llm_wiki 一致,纯嵌入式,Rust 原生绑定)
4. **知识图谱视图**: 4-signal 相关性,简单 React Flow 渲染

### 不做(MVP 范围外)

- ❌ Chrome Web Clipper(浏览器扩展)
- ❌ Deep Research 模块(自动网络检索+合成)
- ❌ Async Review System(LLM 提议、人类审阅)
- ❌ Multi-format 文档解析(PDF/DOCX/PPTX/图像) — 后续 phase
- ❌ MCP server(对外暴露给 Agent)
- ❌ `poml`/模板化 prompt 框架(用字符串模板先跑通)
- ❌ Web 搜索工具接入(在 chat 中可走现有 web_search 工具)

## 架构设计

### 总体方向: **保留 Rust 侧,补齐 LLM**

文件 I/O 已在 Rust,改动最小、性能最佳。LLM 调用走 **Rust 直调 LLM 端点**(`reqwest`,已就绪),与 `llm_wiki` 一致 — 不绕 Python。

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (React + Zustand)                                   │
│  WikiChat / WikiEditor / WikiSearchBar / WikiGraphView        │
│       ↓ Tauri IPC                                             │
├──────────────────────────────────────────────────────────────┤
│  Rust backend (Tauri v2)                                      │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ wiki/llm_provider.rs   # OpenAI/Anthropic/Ollama/   │     │
│  │                         # Custom 适配 (ProviderConfig)│    │
│  │ wiki/llm_prompts.rs    # 两步 CoT prompt 模板        │     │
│  │ wiki/embeddings.rs     # Embedding 客户端            │     │
│  │ wiki/ingest.rs (改)    # 复制 + LLM 分析 + LLM 写作  │     │
│  │ wiki/chat.rs (改)      # 混合检索 + LLM 综合         │     │
│  │ wiki/search.rs (改)    # token 评分 + 向量 RRF       │     │
│  │ wiki/vectorstore.rs    # LanceDB 嵌入式              │     │
│  │ wiki/graph.rs (新)     # 4-signal 知识图谱           │     │
│  │ wiki/commands.rs (扩)  # +6 个 Tauri 命令            │     │
│  └──────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
                ↓ reqwest (rustls-tls)
                ↓ HTTPS / HTTP
                ↓
        OpenAI / Anthropic / Ollama / 自定义 LLM 端点
```

### wiki 目录结构(沿用现状,扩展内容)

```
wiki-project/
├── purpose.md            # 新增: wiki "灵魂",由用户在创建时填写
├── schema.md             # 已有(可由 LLM 自动生成)
├── raw/
│   ├── sources/          # 不可变源文档
│   └── assets/           # 附件
├── wiki/
│   ├── entities/         # 实体页面(人物/组织/产品)
│   ├── concepts/         # 概念页面(理论/方法)
│   ├── sources/          # 源文档摘要
│   ├── queries/          # 查询结果归档
│   ├── overview.md
│   ├── index.md          # 自动维护
│   └── log.md            # 自动维护
└── .llm-wiki/            # 新增: 应用内部状态(不进 git)
    ├── project.json
    ├── ingest-cache.json # SHA256 文件缓存,跳过未变更
    ├── lancedb/          # 向量库
    └── graph-cache.json  # 图谱快照
```

### 页面 frontmatter 规范(对齐 llm_wiki)

```markdown
---
title: Albert Einstein
type: entity           # entity | concept | source | query | synthesis
tags: [physicist, nobel-prize]
related: [[Theory of Relativity]] [[Nobel Prize]]
sources: [raw/sources/einstein-bio.pdf]
created: 2026-06-12
updated: 2026-06-12
---

# Albert Einstein

1879–1955,德国物理学家,相对论提出者。

## 核心贡献

- 狭义相对论(1905)
- 广义相对论(1915)
- 解释光电效应(1921 诺贝尔奖)
```

`related` 字段的 `[[wikilink]]` 解析为图谱边,`sources` 字段追踪真实出处,`tags` 复用为图谱类型亲和信号。

## 阶段分解(8 个 Phase)

### Phase 1: LLM Provider 抽象层 (Rust)

> **目标**: 让 `ingest` / `chat` 都能用一套接口调多 provider

**新建**:
- `src-tauri/src/wiki/llm_provider.rs` (~250 行)
  - `LlmProviderConfig { provider, base_url, api_key, model, max_tokens, temperature, custom_headers }`
  - `Provider` enum: `OpenAI | Anthropic | Ollama | Custom`
  - `trait LlmProvider { fn chat(&self, req: ChatRequest) -> Result<ChatResponse>; fn chat_stream(&self, ...) -> impl Stream; }`
  - 实现 4 个 provider 的 `build_request_body` / `parse_response` / `parse_stream_chunk`
  - **Anthropic provider 注意事项**: 需要 `x-api-key` + `anthropic-version: 2023-06-01` 头,正文用 `messages[].content` 数组结构
  - **Ollama provider**: 默认 base_url `http://localhost:11434/v1`,无 api_key
  - **Custom**: 由用户填写 base_url + 头,按 OpenAI 协议走
- `src-tauri/src/wiki/llm_prompts.rs` (~100 行)
  - 集中放所有 prompt 字符串常量(便于迭代)
  - 不引入 `poml` 之类的框架,纯 `format!()` 模板

**验证**:
- 单元测试: 4 个 provider 的请求构造 + 响应解析(用 mock JSON 字符串)
- 手工 E2E: 用 `curl` 等价的 reqwest 调本地 Ollama 验证

**风险**:
- 中: 4 个 provider 的协议细节容易出 bug(Anthropic 尤其),需要充分测试

---

### Phase 2: 嵌入式向量存储 (LanceDB)

> **目标**: 在 wiki 项目内提供向量检索能力

**新建**:
- `src-tauri/src/wiki/vectorstore.rs` (~300 行)
  - 引入依赖: `lancedb = "0.13"` + `arrow = "53"` + `lance = "0.10"`(用最新稳定版)
  - **注意**: LanceDB 0.27 是 llm_wiki 用的版本,本计划用 0.13 起是因为发布时间稳定;实际版本选 `cargo add` 时挑无 edition2024 限制的最新版
  - `struct ChunkRecord { id, page_path, chunk_index, content, vector: Vec<f32> }`
  - `VectorStore` 包装 LanceDB 表:
    - `open(project_root) -> Result<Self>` — 打开 `.llm-wiki/lancedb/`
    - `upsert(page_path, chunks) -> Result<()>`
    - `delete_by_page(page_path) -> Result<()>`
    - `search(query_vec, limit) -> Result<Vec<(String, f32)>>` — 返回 `(path, score)`
- `src-tauri/src/wiki/embeddings.rs` (~200 行)
  - `EmbeddingClient` 包装 OpenAI 兼容 embeddings 端点
  - `chunk_markdown(content: &str) -> Vec<String>` — 按段落分块,~500 字符/块
  - `embed(texts: &[String]) -> Result<Vec<Vec<f32>>>`
  - 与 `LlmProviderConfig` 共用 base_url + api_key

**修改**:
- `src-tauri/Cargo.toml`: 添加 `lancedb` `arrow` `lance` 依赖
- `src-tauri/src/wiki/mod.rs`: 导出新模块
- `src-tauri/src/wiki/util.rs`: 加 `pub fn chunk_markdown()`(也可放 embeddings.rs,自选)

**验证**:
- 单元测试: 写入 10 个 chunk → 搜索 top-3 → 验证 cosine 排序
- 单元测试: 删除某页 → 重新搜索应无结果
- 集成测试: 用 `mokas`/`wiremock-rs` mock embedding 端点

**风险**:
- **高**: LanceDB Rust crate 还在快速迭代,API 不稳定 — **pin 住版本**,不追 `latest`
- 高: LanceDB 在 Windows 平台可能缺原生二进制;`lancedb` 自带 sqlite-vec fallback,可接受
- 中: embedding 维度与模型绑定,需要 schema migration(本计划先固定 1536 维,迁移留 TODO)

---

### Phase 3: LLM 驱动 Ingest (两步 CoT)

> **目标**: 源文档 → LLM 分析 → LLM 写作 → 结构化 wiki 页面

**修改**:
- `src-tauri/src/wiki/ingest.rs` (重写, ~250 行)
  - 入口: `ingest_source(source_file_path, project_root, llm_config) -> Result<IngestResult>`
  - 流程:
    1. 复制文件到 `raw/sources/`
    2. 计算 SHA256,与 `ingest-cache.json` 对比;命中则跳过
    3. 读取文件内容(限 50KB,超出截断)
    4. **Step 1 — LLM 分析**: 调 LLM 一次,提取 `Analysis { entities, concepts, tags, related_concepts, summary }`
       - Prompt: "阅读以下源文档,提取主要实体、概念、标签、相关主题。输出 JSON。"
       - 输出格式约束: 严格 JSON(用 `temperature=0.0` 强约束)
    5. **Step 2 — LLM 写作**: 调 LLM 一次,基于 `Analysis` 写作
       - Prompt: "基于以下源文档和分析结果,生成 wiki 页面,包含 frontmatter(...)、摘要、关键观点、相关页面链接 `[[...]]`。"
       - 输出: 完整 markdown
    6. 解析 markdown 提取 `related` 字段(`[[wikilinks]]` 扫描)
    7. 写入 `wiki/sources/{slug}.md`
    8. **可选**: 生成 1+ 个 `wiki/entities/*.md` / `wiki/concepts/*.md` 页面(根据 Analysis)
    9. 更新 `index.md` / `log.md`
    10. 调 `VectorStore.upsert(page_path, chunks)`,同时嵌入并存储所有新建页面
    11. 写入 `ingest-cache.json`

**新建**:
- `src-tauri/src/wiki/frontmatter.rs` (~100 行)
  - `parse_frontmatter(content) -> (Frontmatter, body)`
  - `serialize_frontmatter(fm) -> String`
  - `extract_wikilinks(content) -> Vec<String>`
  - 用纯字符串解析(不引 `serde_yaml`,减少依赖)

**Prompt 模板**(写进 `llm_prompts.rs`):

```rust
pub const STEP1_ANALYZE: &str = r#"You are analyzing a source document for a personal wiki.
Output a JSON object with these fields:
- entities: list of {{name, type, brief}}
- concepts: list of {{name, brief}}
- tags: list of 3-7 short strings
- related_topics: list of short strings
- summary: 2-3 sentence summary

SOURCE:
{source_content}

JSON:"#;

pub const STEP2_WRITE: &str = r#"You are writing a wiki page based on a source document.
Use the provided analysis to structure the page.

Output format:
---
title: <Chinese title>
type: source
tags: [a, b, c]
related: [[X]] [[Y]]
sources: [raw/sources/{filename}]
created: {today}
updated: {today}
---

# <title>

<2-4 paragraph summary>

## 关键观点

- ...

## 相关页面

- [[X]] — brief
- [[Y]] — brief

SOURCE CONTENT (truncated):
{content}

ANALYSIS JSON:
{analysis}

Now write the page:"#;
```

**验证**:
- 单元测试: frontmatter 解析/序列化
- 单元测试: wikilink 提取
- 集成测试(用 mock LLM,返回预设 JSON + markdown): 端到端 ingest 一次,验证文件结构
- 手工 E2E: 导入一个 PDF(MinerU 解析后)/Markdown 文件,验证生成页面

**风险**:
- **高**: LLM 输出的 markdown 可能格式不规范 — 需严格 prompt + 输出后正则修正
- 高: 两次 LLM 调用延迟长(10-30s),需要进度反馈(返回 `IngestResult.progress` 字段?)
- 中: Step 1 的 JSON 解析失败需要降级: 重试一次 / 改用宽松正则 / 留 raw text

---

### Phase 4: RAG 增强的 Wiki Chat

> **目标**: 检索 + LLM 综合,带引用

**修改**:
- `src-tauri/src/wiki/chat.rs` (重写, ~300 行)
  - 入口: `chat_with_wiki(query, project_root, llm_config) -> Result<WikiChatResponse>`
  - 流程:
    1. **Token 检索**(`search_wiki`,现状保留)
    2. **向量检索**(`VectorStore.search(query_embedding, limit=20)`)
    3. **RRF 融合**(Reciprocal Rank Fusion): `score = Σ 1/(k + rank_i)`,k=60
    4. **Token 预算分配**(`context_budget.rs`):
       - 总预算 = `min(model_max_tokens * 0.7, 8192)`
       - 50% 给检索结果
       - 30% 给历史消息
       - 5% 给 `index.md`
       - 15% 留给 LLM 输出
       - 单页硬上限 = 总预算 / 8(防止一坨内容压垮)
    5. **拼装 prompt**:
       - system: "你是一个基于用户个人 wiki 回答问题的助手。严格基于提供的 wiki 内容回答,如不相关就说不知道。"
       - context: 截断后的相关页面(`--- 文件: <path> ---\n<content>`)
       - user: 当前问题
    6. **调 LLM**(非流式,MVP 不做流式)
    7. 返回 `WikiChatResponse { answer, citations, retrieval_stats }`
       - `retrieval_stats: { token_hits, vector_hits, fused_top_score, total_context_tokens }` — 前端可显示

**新建**:
- `src-tauri/src/wiki/context_budget.rs` (~150 行)
  - `ContextBudget { total, pages, history, index, response_reserve, per_page_cap }`
  - `compute_budget(model_max_tokens: u32) -> ContextBudget`
  - `truncate_pages(pages: &mut Vec<Page>, budget: &ContextBudget) -> ()` — 按比例截断
  - 极简 token 计数: `text.len() / 3` (UTF-8 平均),不引 `tiktoken-rs`(MVP 简化)

- `src-tauri/src/wiki/rrf.rs` (~50 行)
  - `fn fuse<T: Hash + Eq>(token_hits: Vec<T>, vector_hits: Vec<T>, k: f32) -> Vec<(T, f32)>`

**验证**:
- 单元测试: RRF 融合正确性(已知排序的两个列表,验证融合结果)
- 单元测试: context_budget 截断(给 10 个 page,验证只保留前 N 个)
- 单元测试: prompt 拼装(给 mock 检索结果,验证最终 prompt 包含引用标记)
- 集成测试(用 mock LLM): 端到端问"X 是什么",验证引用 `[[X]]` 出现

**风险**:
- 中: 极简 token 计数可能不准确,但 MVP 可接受
- 中: 单一查询超时(LLM 30s+)时,需要前端 loading 状态 + 错误提示

---

### Phase 5: 知识图谱生成 (4-signal 评分)

> **目标**: 解析所有 wiki 页面 → 构建节点和边 → 计算相关性

**新建**:
- `src-tauri/src/wiki/graph.rs` (~350 行)
  - `struct GraphNode { id, label, type: PageType, sources: Vec<String> }`
  - `struct GraphEdge { source, target, signal: SignalType, weight: f32 }`
  - `enum SignalType { DirectLink, SourceOverlap, TypeAffinity }` (Adamic-Adar 留 TODO)
  - 边类型:
    - `DirectLink` (×3.0): `[[wikilink]]` 出现即加边
    - `SourceOverlap` (×4.0): 两页 `sources: []` 字段共享源文件数 / 总数
    - `TypeAffinity` (×1.0): 同 `type` 字段加边(权重低,做背景)
  - `build_graph(project_root) -> Result<GraphData>` — 全量扫描
  - 缓存到 `.llm-wiki/graph-cache.json`,用 `index.md` 的 mtime 作 key
  - `fn relevance(query, graph, k_hops=2) -> HashMap<NodeId, f32>` — 2 跳扩散,从 query 命中的节点出发

**Tauri 命令**:
- `wiki_get_graph(project_path, query: Option<String>, limit: u32) -> Result<GraphData>`

**验证**:
- 单元测试: 3 节点直接链接 → 1 条 DirectLink 边
- 单元测试: 2 节点共享 2 个 source → SourceOverlap 边权重正确
- 单元测试: 缓存命中时跳过重建

**风险**:
- 低: 解析 markdown 的 `[[wikilinks]]` 需要小心 `[[X|Y]]`(带显示文本)、`![[X]]`(嵌入) 等变体

---

### Phase 6: 知识图谱视图 (前端)

> **目标**: 用 React Flow 渲染图谱,支持点击节点跳转

**新建**:
- `src/widgets/wiki/WikiGraphView.tsx` (~300 行)
  - 引入 `reactflow` (~12.x,纯前端图库,无需后端)
  - 节点 = wiki 页面,颜色按 `type` 区分
  - 边粗细 = `signal weight`
  - 节点 hover → 显示 frontmatter 摘要
  - 节点 click → `openFile(path)` + 切到 browser view
  - 顶部搜索框 → 输入 query → 高亮相关节点
  - 边类型 legend(图例)

**修改**:
- `src/widgets/wiki/WikiToolbar.tsx`: 加 `graph` 视图
- `src/entities/wiki/store.ts`: 加 `graphData: GraphData | null` + `loadGraph(query?)`
- `src/shared/types/wiki.ts`: 加 `GraphNode` / `GraphEdge` / `GraphData` / `PageType`
- `src/shared/api-client/wiki.ts`: 加 `getWikiGraph()` wrapper

**依赖**:
- `npm install reactflow` (注意: 12.x 后改名为 `@xyflow/react`,可选)

**验证**:
- 组件测试: 渲染 mock GraphData,验证节点/边数量
- E2E (Playwright): 打开项目 → 切到 graph view → 看到节点

**风险**:
- 中: 大 wiki (>500 页面) 时图谱渲染卡顿 — 加 limit=100 默认,按 relevance 排序

---

### Phase 7: 进度反馈 + UI 整合

> **目标**: 把 ingest 和 chat 接到 UI,带进度条和流式更新

**新建**:
- `src/widgets/wiki/WikiIngestProgress.tsx` (~150 行)
  - 调 `wikiIngestSource` 时显示进度(分阶段:复制→分析→写作→embedding)
  - 用 Tauri event: `listen('wiki-ingest-{id}-progress', ...)` (Tauri 侧 emit,需新增)
  - 错误时显示"重试"/"跳过"

- `src/widgets/wiki/WikiChat.tsx` (重写)
  - **流式回答**: 把 `wikiChat` 拆成 `wikiChatStream`,Tauri 端 SSE 推 `chunk`
  - 引用列表保持,每条 citation 可点击跳转
  - 显示 `retrieval_stats` 折叠面板(给高级用户)

**修改**:
- `src-tauri/src/wiki/commands.rs`:
  - `wiki_ingest_source` 加 `ingest_id: String`,emit `wiki-ingest-{id}-progress` event
  - `wiki_chat` → 拆成 `wiki_chat` (非流式) + `wiki_chat_stream` (流式)
- `src-tauri/src/wiki/ingest.rs`: 在关键阶段 emit progress
- `src-tauri/src/wiki/chat.rs`: 把流式 LLM 响应经 Tauri event 推到前端

**新建** (前端 hook):
- `src/features/wiki/useWikiIngest.ts` — 封装 ingest 流程 + 进度订阅
- `src/features/wiki/useWikiChatStream.ts` — 封装流式 chat 订阅

**修改**:
- `src/widgets/wiki/WikiToolbar.tsx`: 加"导入文档"按钮(用 Tauri dialog 选择文件)
- `src/widgets/wiki/WikiSearch.tsx`: 搜索结果带 "在 chat 中询问" 按钮

**验证**:
- E2E (Playwright): 选文件 → 看到进度 → 1-2 分钟后看到新页面
- E2E: 提问 → 流式看到答案累积

**风险**:
- 中: LLM 调用阻塞时间长(30s+),用户可能误以为卡死 — 必须有明确进度文字
- 中: 流式响应中断时(网络),需要部分保存 + 重连

---

### Phase 8: 测试 + 文档 + 端到端验证

> **目标**: 80%+ 测试覆盖,所有文档同步,CI 全绿

**新增测试** (Rust):
- `src-tauri/src/wiki/llm_provider.rs`: 4 个 provider 的请求构造/响应解析
- `src-tauri/src/wiki/frontmatter.rs`: 解析/序列化/wikilink 提取
- `src-tauri/src/wiki/rrf.rs`: 融合正确性
- `src-tauri/src/wiki/context_budget.rs`: 截断逻辑
- `src-tauri/src/wiki/graph.rs`: 4-signal 边构建
- `src-tauri/src/wiki/ingest.rs`: 用 mock LLM 端到端

**新增测试** (前端):
- `src/widgets/wiki/WikiGraphView.test.tsx`: mock GraphData,验证节点渲染
- `src/features/wiki/useWikiChatStream.test.ts`: mock Tauri event,验证 chunk 累积

**端到端测试** (Playwright):
- `tests/e2e/wiki-ingest.spec.ts`: 选文件 → 等 ingest 完成 → 看到新页面
- `tests/e2e/wiki-chat.spec.ts`: 提问 → 看到流式答案 + 引用

**文档**:
- `docs/technical/25-llm-wiki-integration.md`(新增): 完整章节,覆盖架构、provider、ingest、RAG、图谱
- `docs/user-manual/03-wiki.md`(新增): 用户手册,如何导入文档、提问、查看图谱
- `docs/technical/README.md`: 章节目录加 25
- `docs/user-manual/README.md`: 加 03

**质量门**:
- `cargo check --manifest-path src-tauri/Cargo.toml` 通过
- `npm run typecheck` 通过
- `npm run test` (vitest) 通过
- `pytest backend/tests` 通过(无需新增 Python 测试)
- 手工 E2E: 1 个真实 wiki 项目的完整流程(导入 3 篇 → 问 5 个问题 → 看图谱)

**风险**:
- 低

---

## 涉及文件清单

### 新建(Rust)

| 文件 | 阶段 | 行数估 |
|---|---|---|
| `src-tauri/src/wiki/llm_provider.rs` | 1 | ~250 |
| `src-tauri/src/wiki/llm_prompts.rs` | 1 | ~100 |
| `src-tauri/src/wiki/vectorstore.rs` | 2 | ~300 |
| `src-tauri/src/wiki/embeddings.rs` | 2 | ~200 |
| `src-tauri/src/wiki/frontmatter.rs` | 3 | ~100 |
| `src-tauri/src/wiki/context_budget.rs` | 4 | ~150 |
| `src-tauri/src/wiki/rrf.rs` | 4 | ~50 |
| `src-tauri/src/wiki/graph.rs` | 5 | ~350 |

### 修改(Rust)

| 文件 | 阶段 | 改动 |
|---|---|---|
| `src-tauri/Cargo.toml` | 2 | 加 `lancedb` `arrow` `lance` |
| `src-tauri/src/wiki/mod.rs` | 1,2,3,4,5 | 导出新模块 |
| `src-tauri/src/wiki/ingest.rs` | 3 | 重写(LLM 集成) |
| `src-tauri/src/wiki/chat.rs` | 4 | 重写(RAG + LLM) |
| `src-tauri/src/wiki/search.rs` | 4 | 加 RRF 融合(可选,核心检索可放在 chat.rs) |
| `src-tauri/src/wiki/commands.rs` | 1,2,3,4,5,7 | +6 个 Tauri 命令 |
| `src-tauri/src/wiki/util.rs` | 2,3 | 加 `chunk_markdown` / `ingest_cache` |

### 新建(前端)

| 文件 | 阶段 | 行数估 |
|---|---|---|
| `src/widgets/wiki/WikiGraphView.tsx` | 6 | ~300 |
| `src/widgets/wiki/WikiIngestProgress.tsx` | 7 | ~150 |
| `src/features/wiki/useWikiIngest.ts` | 7 | ~120 |
| `src/features/wiki/useWikiChatStream.ts` | 7 | ~120 |

### 修改(前端)

| 文件 | 阶段 | 改动 |
|---|---|---|
| `src/widgets/wiki/WikiChat.tsx` | 7 | 重写流式 |
| `src/widgets/wiki/WikiToolbar.tsx` | 6,7 | 加 graph 视图 + 导入按钮 |
| `src/widgets/wiki/WikiSearch.tsx` | 7 | "在 chat 中询问"按钮 |
| `src/entities/wiki/store.ts` | 6,7 | 加 graphData + ingest state |
| `src/shared/types/wiki.ts` | 5,6 | 加 GraphNode/Edge/Data/PageType |
| `src/shared/api-client/wiki.ts` | 5,6,7 | 加 getWikiGraph + 流式包装 |
| `package.json` | 6 | 加 `reactflow` |

### 文档

| 文件 | 阶段 |
|---|---|
| `docs/technical/25-llm-wiki-integration.md` | 8(新) |
| `docs/technical/README.md` | 8 |
| `docs/user-manual/03-wiki.md` | 8(新) |
| `docs/user-manual/README.md` | 8 |
| `docs/plans/2026-06-12_llm-wiki-llm-integration.md` | 当前(完成后归档入技术手册) |

## 实施顺序与里程碑

```
Phase 1 (LLM Provider)
   ↓
Phase 2 (VectorStore + Embeddings) ─┐
   ↓                                │
Phase 3 (Ingest 集成 LLM) ←────────┘ (需要 Provider + VectorStore)
   ↓
Phase 4 (RAG Chat) ←──── (需要 Provider + VectorStore)
   ↓
Phase 5 (Graph 构建) ←── (需要 Phase 3 写完页面)
   ↓
Phase 6 (Graph UI)
   ↓
Phase 7 (进度 + 流式 UI)
   ↓
Phase 8 (测试 + 文档)
```

**预计工时**:

| Phase | 估时 |
|---|---|
| 1. LLM Provider | 1.5 天 |
| 2. VectorStore + Embeddings | 1.5 天 |
| 3. Ingest 两步 CoT | 2 天 |
| 4. RAG Chat | 1.5 天 |
| 5. Graph 构建 | 1 天 |
| 6. Graph UI | 1 天 |
| 7. 进度 + 流式 UI | 1.5 天 |
| 8. 测试 + 文档 | 1 天 |
| **合计** | **11 天** |

## 风险评估

| 风险 | 级别 | 缓解措施 |
|---|---|---|
| LanceDB Rust API 不稳定 | 高 | pin 住版本,加 cargo deny 限制 |
| LLM 输出格式不规范 | 高 | 严格 prompt + JSON mode(temperature=0)+ 输出后正则修复 + 失败重试 |
| Anthropic/Ollama/Custom provider 协议细节 bug | 中 | 单元测试覆盖所有 provider,加 mock 测试 |
| Step 1 + Step 2 延迟长(20-60s) | 中 | 进度反馈(event)+ UI loading;缓存 SHA256 跳过未变 |
| 大 wiki 图谱渲染卡顿 | 中 | 默认 limit=100 节点,按 relevance 排序 |
| 极简 token 计数不准确 | 中 | 留口子,后续接 `tiktoken-rs` |
| Embedding 维度变更 schema 迁移 | 中 | MVP 固定 1536 维,迁移留 TODO |
| 流式响应中断 | 低 | 部分保存 + 重连机制 |
| LLM API key 泄露(传到 Rust) | 低 | 仅内存持有,不入 log,前端不持久化 |

## 验证标准(Definition of Done)

### 功能验收

- [ ] 创建 wiki 项目,填写 `purpose.md`
- [ ] 导入 1 个 Markdown 文件,30 秒内看到 `wiki/sources/*.md` 生成
- [ ] 导入 3 个文件,看到 `index.md` / `log.md` 更新,entities/concepts 页面正确归类
- [ ] 在 chat 中提问,得到**带 wikilink 引用**的回答,引用可点击跳转
- [ ] 切到 graph view,看到节点(按 type 颜色区分)+ 边(按 weight 粗细)
- [ ] 4 个 provider 各测 1 次: OpenAI、Anthropic、Ollama、自定义 OpenAI 兼容
- [ ] 导入同名文件但内容变了(SHA 不同),触发重新 ingest
- [ ] 删除 wiki 文件,向量库和图谱同步更新

### 质量验收

- [ ] 80%+ 测试覆盖(Rust + TypeScript)
- [ ] `cargo check` 通过
- [ ] `npm run typecheck` 通过
- [ ] `npm run test` 通过
- [ ] 所有现有测试不回归
- [ ] 无新增 `console.log` / `eprintln!` / `unwrap()`(在错误路径)
- [ ] `docs/technical/25-llm-wiki-integration.md` 完成
- [ ] `docs/user-manual/03-wiki.md` 完成

### 跨平台验收

- [ ] Windows 10/11 (Tauri 2.1.1)
- [ ] macOS (Tauri 2.1.1)
- [ ] Ubuntu 22.04 (Tauri 2.1.1)
- [ ] Win7 兼容分支不受影响(wiki 改动不进 win7 fork)

## 已确认决策(2026-06-12)

| 决策点 | 选定方案 | 理由 |
|---|---|---|
| 向量存储 | **LanceDB** | 纯嵌入式,与 llm_wiki 一致,Rust 原生绑定最干净 |
| 知识图谱库 | **React Flow** | 纯 React,与 FSD 架构无缝,交互友好 |
| LLM Provider 范围 | **4 个标准 provider** (OpenAI / Anthropic / Ollama / Custom) | 覆盖 95% 用例,工作量可控 |
| 独立 PR | **PR-8 单独发布** | 18 个文件,1500+ 行,独立 review |
| Embedding 维度 | **固定 1536 维** (text-embedding-3-small) | MVP 简化,迁移留 TODO |

## 关联文档

- 上游: `docs/plans/2026-05-30_llm-wiki.md`(Phase 1-5 已完成,本计划承接)
- 参考实现: `/home/fz/project/llm_wiki`(完整 Rust + React + LanceDB 实现)
- 上游 wiki 文档: `docs/technical/24-skills-system.md`(Skills bounded context 范本)
- 六边形架构: `docs/technical/18-hexagonal.md`(本计划不破六边形,文件 I/O 在 Rust 保持不变)
- LLM 客户端: `backend/adapters/out/llm/httpx_adapter.py`(Python 端参考,Rust 端独立实现)

---

## 状态追踪

实施时更新此节:

- [x] 计划创建
- [ ] Phase 1: LLM Provider 抽象层
- [ ] Phase 2: 嵌入式向量存储 (LanceDB)
- [ ] Phase 3: LLM 驱动 Ingest (两步 CoT)
- [ ] Phase 4: RAG 增强的 Wiki Chat
- [ ] Phase 5: 知识图谱生成 (4-signal)
- [ ] Phase 6: 知识图谱视图 (前端)
- [ ] Phase 7: 进度反馈 + UI 整合
- [ ] Phase 8: 测试 + 文档 + 端到端验证
