# Wiki 嵌入模型改为可选（对齐 llm_wiki）

- 日期：2026-11-15
- 分支：`feat/wiki-optional-embedding`（基于 `origin/main`，当前 main 已含 #3084）
- 参考实现：`/home/fz/project/llm_wiki`（Tauri）

## 1. 背景

参考项目 llm_wiki 的嵌入是**可选能力，默认关闭**：

- `src/stores/wiki-store.ts:649-654` — `embeddingConfig.enabled` 默认 `false`
- `src/lib/ingest.ts:1559` — 导入 Step 6 仅在 `enabled && model` 时执行，且每个
  `embedPage` 的异常被吞掉（`catch { /* non-critical */ }`）
- `src/lib/dedup-runner.ts:200`、`src/lib/deep-research.ts:693` — 同类门控
- `llm-wiki.md:47` — 主检索靠 `index.md` + LLM 下钻，明确"避免 embedding-based RAG 基础设施"

Sage 当前实现有两个卡点：

1. `embed_pages`（`backend/wiki/ingest.py`）是导入必经步骤：未配置嵌入模型时请求会打空
   base_url、失败即中断导入；#3084 之后前端直接拦截导入并提示先配置。
2. 向量维度硬编码 1536（`DEFAULT_EMBED_DIM`）：用 1024 维模型（如 bge-m3）会
   `parse_embed_response` 报维度不匹配，导入失败；聊天检索也只能降级 token 搜索。

## 2. 目标

1. 未配置嵌入模型时，导入照常完成（跳过向量化），进度条给出明确提示。
2. 已配置但嵌入调用/解析/写库失败时，**非致命**：记录日志、继续完成导入。
3. 向量维度从嵌入响应自适应（不再硬编码 1536）；模型切换导致维度变化时自动重置
   wiki 向量库（派生数据，可重建），与 `backend/zotero/ingest.py` 既有模式一致。
4. 摄入队列（queue worker）同样允许无嵌入配置。
5. Wiki 问答保持现有降级（token 检索），但支持非 1536 维模型参与向量检索。

## 3. 设计决策

- **不做显式 enable 开关**：Sage 的 `modelSelections.embeddingModel` 未配置（endpointId 或
  modelId 为空）即视为关闭，与现有设置模型一致，避免新增状态。
- **embed_pages 改为"尽力而为"**：返回 `Optional[int]`（写入维度）；跳过/失败返回 `None`，
  不抛异常。同步 `ingest_source` 与流式 `ingest_source_stream` 都复用。
- **维度重置策略**：读取现有 `vectors.json` 的 `dim`（复用
  `backend/wiki/vectorstore.py::read_stored_dim`），与本次响应维度不同时：
  记 warning + 删除旧 `vectors.json`（JSON 后端），再按新维度创建。HNSW 后端维度
  不匹配的异常同样被吞掉（日志告警），检索层本来就会降级。
- **聊天检索自适应**：`parse_embed_response(body, 0)` 取实际维度后再打开向量库；
  维度不匹配沿用现有 try/except 降级 token 搜索。
- **路由请求模型**：`IngestRequest` / `ChatRequest` 的 `embed_*` 字段给默认空串，
  允许调用方完全省略嵌入配置（前端仍显式传值）。

## 4. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `backend/wiki/ingest.py` | `embed_pages` 可选/失败非致命/维度自适应 + 重置；sync/stream 的 embedding 进度文案区分跳过 |
| `backend/wiki/chat.py` | 查询向量维度自适应；不再依赖 `embed_dim` |
| `backend/wiki/queue_worker.py` | embedding 配置可选（仅 LLM 必填） |
| `backend/api/wiki_routes.py` | `IngestRequest`/`ChatRequest` 的 `embed_*` 默认空串 |
| `src/widgets/wiki/SourcesView.tsx` | 移除"未配置嵌入模型"拦截；未配置时 `toast.info` 提示并继续导入（embed 字段传空） |
| `backend/tests/integration/test_ingest_stream.py` | 新增：未配置嵌入仍 completed；嵌入失败非致命；1024 维写入；维度变更重置向量库 |
| `backend/tests/unit/wiki/test_queue_worker.py` | 更新：仅缺 LLM 报错；缺 embedding 正常处理 |
| `src/widgets/wiki/__tests__/SourcesView.test.tsx` | 更新：未配置嵌入仍导入并提示，不再拦截 |
| `docs/user-manual/03-wiki.md` | 嵌入改为可选；更新 Q4/Q5 |
| `docs/technical/25-llm-wiki-integration.md` | 补充"嵌入可选 + 自适应维度"说明 |

## 5. 实施步骤

- [x] M1 `embed_pages` 可选/非致命/自适应维度 + 向量库重置
- [x] M2 `ingest_source` / `ingest_source_stream` 进度文案（跳过 vs 执行）
- [x] M3 `chat.py` 查询维度自适应
- [x] M4 `queue_worker.py` 嵌入可选 + 路由请求模型默认值
- [x] M5 前端 SourcesView 放行 + 提示 + 测试
- [x] M6 后端/前端测试、ruff、py38 兼容、tsc/eslint/prettier、架构棘轮
- [x] M7 文档更新（用户手册 03 / 技术 25）
- [ ] M8 提交、PR、CI 绿后合并
- [ ] M9 cherry-pick 到 `release/win7`（按分支实测补棘轮）并验证

### 本地验证记录

- 后端：wiki 相关 pytest 291 passed（含新增 4 个嵌入用例 + 队列用例拆分）；
  `ruff check` 通过；`check_py38_compat.py` 0 violations。
- 前端：`vitest run src/widgets/wiki src/features/wiki` 23 文件 / 99 tests passed（SourcesView 新增"无嵌入仍导入"用例）；
  `tsc --noEmit`、eslint、prettier 通过。
- 架构棘轮：按 ratchet 协议补账 `wiki_routes.py` 1856→1858、`ingest.py` 873→946，
  `architecture-check.mjs` 通过。

## 6. 风险与依赖

- **维度变更会清空 wiki 向量库**：向量是派生数据，wiki 页面不受影响；需在用户手册
  写明"切换嵌入模型后旧页面需重新导入以恢复向量检索"。与 zotero 既有行为一致。
- **嵌入失败静默**：仅写后端日志 + 进度条提示跳过/失败；不会中断导入。聊天侧原本即降级。
- **HNSW 后端**：维度变化时旧索引无法复用，异常被捕获并告警；默认 JSON 后端行为明确。
- 行为变化：导入不再因嵌入缺失/失败而失败，与 llm_wiki 对齐；测试同步更新。
