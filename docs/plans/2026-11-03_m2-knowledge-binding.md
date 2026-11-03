# M2 计划：知识绑定（KnowledgeBinding）

> 对应 spec: `docs/superpowers/specs/2026-11-03-specialist-persona-design.md` §M2
> 实施分支: `feat/specialist-persona`
> Worktree: `/home/fz/project/sage/.worktrees/feat-specialist-persona`

## 背景与目标

M2 让专家可绑定多个知识源（Wiki/Zotero/项目资料/工作区/专家私有目录），
统一检索返回引用可点击定位。验收条件：

1. 研究专家只能引用绑定的 Zotero 集合与 Wiki 空间；
2. 引用在聊天消息中可点击定位。

## 涉及的文件与模块

### 后端
- `backend/agents/knowledge_binding.py` — 新：`KnowledgeBinding` 数据模型（pydantic v2 BaseModel）
- `backend/data/knowledge_repo.py` — 新：CRUD + 检索查询
- `backend/api/v1/specialist_knowledge_routes.py` — 新：`GET/POST/DELETE /api/v1/specialists/{id}/knowledge`
- `backend/retrieval/rrf.py` — 新：RRF 融合 + 引用输出
- `backend/data/migrations/` — 新迁移脚本：向量表增加 `agent_id` 列 + 索引
- `backend/agents/profiles.py` — 扩展：`AgentProfile.knowledge_bindings: list[KnowledgeBinding]`
- `backend/agents/knowledge_catalog.py` — 扩展：`list_knowledge_sources()` 返回可用源元数据

### 前端
- `src/shared/api/types/domainEntityTypes.ts` — 扩展 `KnowledgeBinding` 接口
- `src/shared/api/specialistKnowledgeApi.ts` — 新：绑定增删查
- `src/widgets/specialists/KnowledgeBindingsEditor.tsx` — 新：专家「知识」Tab 内编辑器
- `src/widgets/chat/MessageReferences.tsx` — 扩展：引用 chip 点击跳转
- `src/pages/Specialists.tsx` — 扩展：卡片点击「编辑知识」打开 Drawer/Dialog

### 数据
- SQLite `vectors` 表增加 `agent_id TEXT` 列 + 索引（null 视为共享层）
- 历史数据迁移：现有向量行 `agent_id` 留空（NULL）

## 技术方案

### 1. KnowledgeBinding 数据模型

```python
class KnowledgeBinding(BaseModel):
    id: str                      # 绑定唯一 ID（短 hash）
    agent_id: str                # 所属专家
    source_type: Literal['wiki', 'zotero_collection', 'project_files', 'workspace', 'specialist_private']
    source_id: str               # 源 ID（wiki_space_id / collection_key / workspace path 等）
    name: str                    # 展示名
    filters: dict[str, Any] = {} # 可选过滤（tag/路径前缀）
    created_at: int
```

### 2. 检索编排

```
query
  ├─ 路由到 binding.source_type 的检索后端
  │   ├─ wiki → wiki.search(space_id, query)
  │   ├─ zotero_collection → zotero.search(collection_key, query)
  │   ├─ project_files → fts(query, project_path)
  │   ├─ workspace → fts(query, workspace_path)
  │   └─ specialist_private → fts(query, ~/.sage/specialists/<id>/knowledge/)
  ├─ 每路返回 (doc, score) 列表
  └─ RRF 融合 top-k
      score(d) = Σ 1 / (k + rank_in_source(d))  k=60
      → 输出 (doc, score, binding_id, source_type, source_id, loc)
```

### 3. 引用点击定位

聊天消息中引用 chip 点击后根据 `loc` 字段：
- wiki → 跳转 wiki 页面锚点
- zotero → 打开 Zotero 条目
- 文件类 → 打开文件 + 滚动到行号

## 实施步骤（分可独立验证的里程碑）

- [ ] **M2-Task 1** 数据模型 + 迁移：`KnowledgeBinding` pydantic 模型；`vectors` 表加 `agent_id` 列+索引；`AgentProfile.knowledge_bindings` 字段扩展
- [ ] **M2-Task 2** CRUD 端点：`GET/POST/DELETE /api/v1/specialists/{id}/knowledge`；前端 `specialistKnowledgeApi`；专家页「知识」Tab 编辑 UI
- [ ] **M2-Task 3** 检索编排：RRF 融合 + 按 binding 路由；后端 `retrieval/rrf.py`；单元测试覆盖三路源融合
- [ ] **M2-Task 4** 引用输出：检索结果带 `loc` 字段；聊天消息引用 chip 点击跳转；E2E smoke 覆盖
- [ ] **M2-Task 5** 拒答策略 + 可观测：无命中时返回结构化 `no_hit` 响应 + 日志 span

## 风险评估与依赖

### 风险
1. **向量表 schema 迁移**：`vectors` 表是 SQLite，`ALTER TABLE ADD COLUMN` 需要 `IF NOT EXISTS` 兜底；已有行 `agent_id` 留 NULL。
2. **RRF 性能**：多源并发查询需要 asyncio.gather + 超时；任一源超时不应拖垮整体。
3. **Zotero API 速率**：检索 Zotero 需 token；未绑定 token 时 source 应被跳过。

### 依赖
- M2 依赖 M1 已落地的 `AgentProfile.knowledge_bindings` 字段（已在 M1-A 加入 schema）。
- M2 依赖 `backend/retrieval/` 已存在的基础检索函数（已存在 `wiki.search`、`zotero.search`、`fts.search`）。

## 验收测试

- 单元测试：`KnowledgeBinding` 序列化/反序列化；RRF 三路融合正确性
- 集成测试：CRUD 端点 200/404/422 覆盖
- E2E smoke：创建专家 → 绑定 Zotero 集合 → 聊天中引用 → chip 可点击
