# M2 计划：知识绑定（KnowledgeBinding）

> 对应 spec: `docs/superpowers/specs/2026-11-03-specialist-persona-design.md` §M2
> 实施分支: `feat/specialist-persona`
> Worktree: `/home/fz/project/sage/.worktrees/feat-specialist-persona`

## 背景与目标

M2 让专家可绑定多个知识源（Wiki/Zotero/项目资料/工作区/专家私有目录），
统一检索返回引用可点击定位。验收条件：

1. 研究专家只能引用绑定的 Zotero 集合与 Wiki 空间；
2. 引用在聊天消息中可点击定位。

## 涉及的文件与模块（实际架构，2026-11-04 调查后更新）

### 向量存储现状（三层异构，非统一抽象）

| 存储 | 后端 | 文件/表 | 命名空间 | 是否有 agent_id |
|---|---|---|---|---|
| Wiki 向量 | `backend/wiki/vectorstore.py` (JSON) | `.llm-wiki/vectors.json` | `page_path` | ❌ |
| 附件向量 | `backend/wiki/vectorstore.py` (JSON) | `{data_root}/rag/attachments.json` | `page_path` (chat-attachment/\<media_id\>) | ❌ |
| 项目资料向量 | `backend/services/project_material_indexer.py` (sqlite-vec) | `project_materials_vec_<dim>` virtual table in main SQLite | `project_id` | ❌ |
| RAG 服务 | `services/rag-service/` (独立进程 :8766) | `data/rag.db` FTS5（**不是向量**） | 无 | ❌ |

**关键发现**：
1. `services/rag-service/` 是 FTS5 全文检索，**不是向量存储**；spec 中「复用 LanceDB」与实际不符
2. 向量存储分散在 JSON 文件（wiki/attachments）和 sqlite-vec（project_materials）两种后端
3. 没有任何一层有 `agent_id` 维度

### M2 实施策略：路由层 + 专家私有向量库（最小改动）

**不修改现有三层存储的 schema**，而是在上层加路由层 + 新建专家私有向量库：

### 后端（新增）
- `backend/agents/knowledge_binding.py` — `KnowledgeBinding` 数据模型（pydantic v2）
- `backend/agents/knowledge_retriever.py` — **路由层**：按 binding.type 扇出到对应检索器
- `backend/agents/specialist_vectorstore.py` — **新**：专家私有向量库（复用 `VectorStore` 抽象，路径 `~/.sage/specialists/<id>/vectors.json`）
- `backend/agents/rrf.py` — RRF 融合算法（纯函数，与存储无关）
- `backend/api/v1/specialist_knowledge_routes.py` — CRUD 端点
- `backend/agents/profiles.py` — 扩展 `AgentProfile.knowledge_bindings: list[KnowledgeBinding]`

### 后端（复用，不改 schema）
- Wiki 检索：通过 `wiki.vectorstore.VectorStore.search()` + `allowed_paths` 过滤
- 项目资料检索：通过 `ProjectMaterialIndexer.search(project_id, ...)`（已按 project_id 过滤）
- Zotero 检索：通过 `zotero.service.semantic_search(query, limit)`（已确认有向量检索，返回 `[{key, score, title, ...}]`）
- 工作区 FTS：通过 `backend.tools.workspace_index` 或现有 FTS5

### 前端
- `src/shared/api/types/domainEntityTypes.ts` — 扩展 `KnowledgeBinding` 接口
- `src/shared/api/specialistKnowledgeApi.ts` — 新：绑定增删查
- `src/widgets/specialists/KnowledgeBindingsEditor.tsx` — 新：专家「知识」Tab 内编辑器
- `src/widgets/chat/MessageReferences.tsx` — 扩展：引用 chip 点击跳转
- `src/pages/Specialists.tsx` — 扩展：卡片点击「编辑知识」打开 Drawer/Dialog

### 数据（新增，不迁移）
- 专家私有向量库：`~/.sage/specialists/<agent_id>/vectors.json`（复用 VectorStore JSON 格式）
- 现有 wiki/project/attachment 向量库**不动**，历史数据无需迁移

## 技术方案（2026-11-04 更新，基于实际架构）

### 1. KnowledgeBinding 数据模型

```python
# backend/agents/knowledge_binding.py
from typing import Literal, Optional
from pydantic import BaseModel, Field

class KnowledgeBinding(BaseModel):
    """知识绑定。source_type 决定检索路由。"""
    id: str                          # 绑定唯一 ID（短 hash）
    agent_id: str                    # 所属专家
    source_type: Literal[
        'wiki_project',              # → wiki.vectorstore.VectorStore
        'zotero_collection',         # → backend.adapters.out.zotero (待查)
        'project_material',          # → services.project_material_indexer
        'workspace_fts',             # → backend.services.workspace_health FTS
        'specialist_private',        # → ~/.sage/specialists/<id>/vectors.json
    ]
    source_id: str                   # 源标识（project_id / collection_key / workspace_path）
    name: str                        # 展示名
    filters: dict = Field(default_factory=dict)  # 可选过滤（tag/路径前缀）
    created_at: int                  # Unix timestamp

    class Config:
        extra = 'forbid'
```

### 2. 检索编排（路由层，不改现有存储）

```
query
  ├─ 遍历 specialist.knowledge_bindings
  │   ├─ wiki_project → VectorStore.open(project_root).search(query_vec, allowed_paths=...)
  │   ├─ project_material → ProjectMaterialIndexer.search(source_id, query)
  │   ├─ specialist_private → VectorStore.open_at(~/.sage/specialists/<id>/vectors.json).search(query_vec)
  │   ├─ zotero_collection → (待查 zotero 适配器是否有向量检索)
  │   └─ workspace_fts → FTS5 查询（非向量）
  ├─ 每路返回 (doc, score) 列表
  └─ RRF 融合 top-k
      score(d) = Σ 1 / (k + rank_in_source(d))  k=60
      → 输出 (doc, score, binding_id, source_type, source_id, loc)
```

**关键点**：
- 路由层负责嵌入查询向量（复用 `backend.wiki.embeddings.build_embed_request`）
- 专家私有向量库复用 `VectorStore` 抽象，路径 `~/.sage/specialists/<agent_id>/vectors.json`
- FTS5 源（workspace）与向量源（wiki/project/specialist）混排时，RRF 仍能工作（rank-based）

### 3. 引用点击定位

聊天消息中引用 chip 点击后根据 `loc` 字段：
- wiki → 跳转 wiki 页面锚点（`/wiki/<project_id>/<page_path>#chunk-<chunk_index>`）
- project_material → 打开资料详情（`/projects/<project_id>/materials/<material_id>`）
- specialist_private → 打开专家私有文件（`/specialists/<agent_id>/knowledge/<path>`）
- zotero → 打开 Zotero 条目（待查 URI 格式）
- workspace_fts → 打开文件 + 滚动到行号

## 实施步骤（分可独立验证的里程碑，2026-11-04 更新）

- [ ] **M2-Task 1** 数据模型：`KnowledgeBinding` pydantic 模型；`AgentProfile.knowledge_bindings` 字段扩展；专家私有向量库 `specialist_vectorstore.py`（复用 VectorStore，路径 `~/.sage/specialists/<id>/vectors.json`）
  - ~~不再需要 SQLite migration~~：现有向量层不动，专家私有库是新 JSON 文件
- [ ] **M2-Task 2** CRUD 端点：`GET/POST/DELETE /api/v1/specialists/{id}/knowledge`；前端 `specialistKnowledgeApi`；专家页「知识」Tab 编辑 UI
- [ ] **M2-Task 3** 检索编排 + RRF：`knowledge_retriever.py` 路由层按 binding.source_type 扇出；`rrf.py` 纯函数融合；单元测试覆盖三路源（wiki/project_material/specialist_private）
- [ ] **M2-Task 4** 引用输出：检索结果带 `loc` 字段（page_path + chunk_index / material_id + chunk_index / file_path + line）；聊天消息引用 chip 点击跳转
- [ ] **M2-Task 5** 拒答策略 + 可观测：无命中时返回结构化 `no_hit` 响应 + 日志 span

## 风险评估与依赖（2026-11-04 更新）

### 风险
1. ~~**向量表 schema 迁移**~~：已规避，不动现有存储
2. **RRF 性能**：多源并发查询需要 asyncio.gather + 超时；任一源超时不应拖垮整体
3. **Zotero API 速率**：检索 Zotero 需 token；未绑定 token 时 source 应被跳过
4. **嵌入模型一致性**：专家私有向量库必须与检索时使用同一嵌入模型（维度对齐）；`VectorStore.open_at` 已有 `dim` 校验
5. **向量库文件大小**：JSON 格式在大量 chunk 下序列化慢；若单专家 > 10k chunks 需考虑切分或迁移到 sqlite-vec

### 依赖
- M2 依赖 M1 已落地的 `AgentProfile` schema（M1-A commit `b7fd21cec`）
- M2 依赖 `wiki.vectorstore.VectorStore` 抽象（已存在，支持 `allowed_paths` 过滤）
- M2 依赖 `services.project_material_indexer.ProjectMaterialIndexer.search()`（已存在，按 project_id 过滤）
- M2 依赖 `zotero.service.semantic_search()`（已存在，返回 `[{key, score, title, ...}]`，RAG 不可用时返回 None）

## 验收测试

- 单元测试：`KnowledgeBinding` 序列化/反序列化；RRF 三路融合正确性
- 集成测试：CRUD 端点 200/404/422 覆盖
- E2E smoke：创建专家 → 绑定 Zotero 集合 → 聊天中引用 → chip 可点击
