# M3 计划：记忆隔离（Memory Isolation）

> 对应 spec: `docs/superpowers/specs/2026-11-03-specialist-persona-design.md` §7 / §M3
> 实施分支: `feat/specialist-persona`
> Worktree: `/home/fz/project/sage/.worktrees/feat-specialist-persona`

## 背景与目标

M3 让每个专家拥有私有记忆层，同时保留共享用户偏好可见性。验收条件：

1. 写作专家与编码专家的私有记忆互不可见；
2. 共享用户偏好双方可见；
3. 删除专家级联清理私有记忆。

## 涉及的文件与模块（2026-11-04 架构调查后确认）

### 现状（调查结论）

- **数据行无 agent 维度**：`memories_episodic` / `memories_semantic` 两张表均无 `agent_id`；
  现有隔离轴只有 `session_id`（working 严格；episodic/semantic 软跨会话）、
  `scope` + `project_key`（user/project/global 可见性）、`allowed_tiers`
  （M0 读层封顶，来自 `agents.memory_access`）。
- **hex 路径共用全局单例**：`backend/memory/registry.py:40` 的
  `get_memory_manager()` 被所有会话/专家共享；legacy 路径每 agent 一个
  manager 但底层表共享。因此隔离**必须做在数据行上**，不能靠多实例。
- **迁移机制**：`backend/data/migrations/runner.py`，v4
  `memories_episodic_columns` 是 PRAGMA 检查 + ALTER 补列的直接模板；
  当前最高版本 v10。
- **会话已带专家归属**：`sessions.specialist_id TEXT DEFAULT 'primary'`
  （database.py:726-729）——**每会话的当前专家身份从会话绑定解析**，
  不依赖请求级参数。
- **FTS5 表只索引正文**（content/summary/tags），agent 过滤必须在主表 JOIN 上做。

### 后端（改动）

| 文件 | 改动 |
|---|---|
| `backend/data/migrations/runner.py` | 新增 v11 迁移：两表 `ADD COLUMN agent_id TEXT` + 复合索引 |
| `backend/data/database.py` | 幂等 ALTER 兜底 + `CREATE INDEX IF NOT EXISTS`（沿用双保险模式） |
| `backend/memory/episodic.py` | `save/search/_search_fts/_search_like` 增加 `agent_id` 过滤参数 |
| `backend/memory/semantic.py` | 同上（`_scope_conditions` 扩展） |
| `backend/memory/manager.py` | `memorize/recall/search_memories/aremember/delete_memory` 增加 `agent_id`；读取语义 = 私有 ∪ 共享 |
| `backend/adapters/out/memory/adapter.py` | `store/retrieve` 传递 `agent_id` |
| `backend/ports/memory.py`（MemoryPort） | `store/retrieve` 签名扩展 |
| `backend/application/services/chat_service.py` | 自动记忆写入传会话专家的 `specialist_id` |
| `backend/tools/context.py` | `ToolExecutionContext` 增加 `agent_id` |
| `backend/tools/memory_tool.py` | 保存/检索从 context 取 agent_id |
| `backend/api/hex_routes.py` / `legacy_routes.py` | 构造 ToolExecutionContext 时传入会话专家 |
| `backend/orchestration/subagent_runner.py` | 子代理子会话继承父 `specialist_id` |
| `backend/api/legacy_memory_list_routes.py` / `legacy_memory_routes.py` | `/memory/list`、`/memory/search` 增加 `agent_id` 过滤；新增 `POST /memory/{id}/promote` |
| `backend/api/specialist_routes.py` | 删除专家时级联清理私有记忆 |

### 前端

| 文件 | 改动 |
|---|---|
| `src/shared/api/memoryApi.ts` | 行类型增加 `agent_id`；`getMemories/searchMemories` 增加 agent 参数；新增 `promoteMemory` |
| `src/widgets/memory/MemoryBrowser.tsx` | 专家筛选下拉（全部/共享/各专家）+ 行内专家徽标 |
| `src/widgets/memory/MemoryItem.tsx` | 专家徽标 + 「提升为共享」按钮（仅私有行） |
| `src/widgets/memory/NewMemoryModal.tsx` | 归属选择（共享 / 指定专家） |
| `src/pages/Memory.tsx` | 导出按当前筛选过滤 |

## 技术方案

### 1. 数据模型：agent_id 作为正交维度

```sql
-- v11 迁移
ALTER TABLE memories_episodic ADD COLUMN agent_id TEXT;      -- NULL = 共享
ALTER TABLE memories_semantic ADD COLUMN agent_id TEXT;
CREATE INDEX IF NOT EXISTS idx_episodic_agent ON memories_episodic(agent_id, scope, project_key);
CREATE INDEX IF NOT EXISTS idx_semantic_agent ON memories_semantic(agent_id, scope, project_key);
```

**语义（fail-safe 默认）**：

| `agent_id` | 含义 | 可见性 |
|---|---|---|
| `NULL` | 共享层（历史数据回填值、用户偏好） | 所有专家可见 |
| `'primary'` | 默认助手私有 | 仅 primary |
| `'specialist-x'` | 专家私有 | 仅 specialist-x |

- **迁移回填**：`agent_id IS NULL` 视为共享层（不迁移历史数据，零风险）。
- **读取过滤**：`WHERE (agent_id = :current OR agent_id IS NULL)`；
  `current` 来自会话绑定 `sessions.specialist_id`。
- **写入默认**：自动抽取记忆写 `agent_id = 会话专家`；用户经 UI 新建默认共享（NULL）。
- **管理视图**：`/memory/list` 带 `agent_id` 参数时按精确匹配过滤
  （`agent_id=shared` 映射 `IS NULL`），无参数时返回全部（管理口径）。

### 2. MemoryPolicy（spec §7.1 落地，最小实现）

`agents.memory_policy`（JSON，列已存在）解析：

```python
# backend/agents/memory_policy.py（新）
class MemoryPolicy(BaseModel):
    read_scopes: List[Literal["specialist", "project", "user"]] = ["specialist", "project", "user"]
    write_scope: Literal["specialist", "project", "user"] = "specialist"
    auto_extract: bool = True
    retention_days: Optional[int] = None
    class Config: extra = "forbid"
```

- `write_scope="specialist"` → 写 `agent_id=当前专家`；
- `write_scope="user"` → 写 `agent_id=NULL`（共享）；
- `read_scopes` 缺 `specialist` 时读取过滤剔除私有行（仅共享/项目/用户）。
- pydantic v1/v2 双兼容（与 `KnowledgeBinding` 同模式）。

### 3. 身份贯穿（最小改动路径）

每会话的专家身份 = `sessions.specialist_id`（已有列，已有 `resolve_bound_specialist_strict`）。

1. `ToolExecutionContext` 增加 `agent_id: str = "primary"`（frozen dataclass 加默认值，避免改动全部构造点的类型错误）；构造点从会话绑定解析传入。
2. `MemoryAdapter.store/retrieve` 增加 `agent_id` 可选参数，显式传参优先于 context。
3. ChatService 自动抽取路径：`resolve` 会话专家 → `memory.store(agent_id=...)`。
4. **子代理继承**（2026-11-04 调查修正）：实际**不存在子会话** —— `SubagentRunner`
   直接把父会话的 `session_id` 传给 `child.run_loop`（LLM 用量归因用），且
   `__call__(task, agent_id)` 的 `agent_id` 是编排角色（researcher/coder…），
   与记忆归属是不同命名空间。因此改为：构造参数新增 `agent_id`，缺省时
   从父会话 `sessions.specialist_id` 解析，再改写子代理运行期的
   `ToolExecutionContext.agent_id`（见 Task 5 实施记录）。
5. memory 工具：`MemorySaveTool` 写 `agent_id=context.agent_id`；`MemorySearchTool` 读 own ∪ shared。

### 4. 提升为共享 / 级联删除

- `POST /api/v1/memory/{id}/promote`：`agent_id → NULL`，写 `memories_evolution_log` 审计行。
- 删除专家（`DELETE /api/v1/specialists/{id}`）：先 `DELETE FROM memories_episodic/semantic WHERE agent_id = ?`，再删专家行；需同步清理向量库条目（`_vector_*` / wiki vectorstore 中该 agent 的记录，若有）。

### 5. 前端

- MemoryBrowser 增加专家筛选（客户端过滤 `agent_id`，与现有 scope 筛选同模式）+ 共享徽标。
- MemoryItem：私有行显示「提升为共享」按钮（二次确认）。
- NewMemoryModal：归属下拉（共享 / 专家列表），默认共享。

## 实施步骤（分可独立验证的里程碑）

- [x] **M3-Task 1** DB 迁移 v11 + 幂等兜底 + 索引；测试：旧库迁移幂等、列与索引存在、NULL 语义 — 完成 2026-11-04；`runner.py` 新增 v11 `memory_agent_columns`（PRAGMA 幂等补 `agent_id TEXT` + 复合索引 `(agent_id, scope, project_key)`），`database.py` 两表 ALTER 兜底 + 索引；存量行不回填（NULL=共享层）；新增 6 个迁移单测（全新库/索引/账本/幂等/旧行可读/v10→v11 升级），`test_schema_migrations` 版本集合同步 11；38 个 memory 测试全绿，ruff + py38 门禁通过
- [x] **M3-Task 2** 存储层过滤：`EpisodicMemory` / `SemanticMemory` 的 save/search 增加 agent 条件；测试：跨 agent 不可见、共享可见 — 完成 2026-11-04；`scope.py` 新增 `agent_visibility_sql`（`agent_id = ? OR agent_id IS NULL`，falsy 返回空片段）+ `is_row_visible` 增加 `current_agent_id` 维度；两存储 `save/_search_fts/_search_like/get_recent` 全路径加可选 `agent_id`（None=不限制，向后兼容）；新增 12 个隔离单测（own/shared/cross × episodic/semantic × fts/like/save/get_recent），memory 全域 66 测试绿，ruff + py38 门禁通过。向量 payload 确认无 agent_id（vec0 仅 embedding/memory_id/memory_type/session_id）——旁路过滤留待 Task 4 在 `is_row_visible` 融合后处理
- [x] **M3-Task 3** `MemoryManager` API 扩展 + `MemoryPolicy` 模型 — 完成 2026-11-04；新增 `backend/agents/memory_policy.py`（pydantic v1/v2 双兼容 `class Config: extra='forbid'`；`parse_memory_policy` fail-safe；`resolve_write_agent_id`/`includes_private_reads` 辅助）；`manager.py` 构造注入 `memory_policy`，`remember/aremember/memorize/compress/recall/get_context*/search_memories/resolve_conflicts/memorize_with_conflict_check` 全路径透传 `agent_id`+`include_private`；`delete_memory` 跨专家私有行保护（agent_id 给定 ≠ 行归属时拒绝）；`conflict.py` `resolve/_find_candidates` 加 agent_id 防跨专家误伤；`semantic._init_fts` 补 `agent_id TEXT` ALTER 兜底（与 `database.init_db` 同款幂等）+ CREATE TABLE 主声明同步加列；新增 20 个单测覆盖（policy 默认/extra=forbid/parse 四态/bad JSON/invalid enum/helper 双态、manager 写默认/写 honor agent、recall 三方集差/get_context 集差/search 三方、policy 写私有/读剔私有/write_scope=user 共享、delete 跨专家拒绝/共享管理路径、resolve_conflicts 同归属）；memory 全域 237 测试绿；ruff + py38 门禁通过
- [x] **M3-Task 4** 身份贯穿：`ToolExecutionContext.agent_id` + ChatService 自动抽取 + memory 工具 + 构造点；测试：会话专家自动归属 — 完成 2026-11-04；`ToolExecutionContext` 增加 `agent_id: str = "primary"`（frozen dataclass 带默认值，构造点零破坏）；`MemoryPort.store/retrieve` 协议签名扩展 `agent_id: Optional[str] = None`，`MemoryAdapter` 透传给 `manager.memorize/recall`，向量召回路径在 RRF 融合后按 `is_row_visible(current_agent_id=agent_id)` 二次过滤（向量 payload 无 agent_id 维度，只能事后过滤）；`ChatService._extract_and_store_memory` 与模块级 `extract_and_store_memory` 在 `agent_id is None` 时用 `resolve_bound_specialist(session_id)` 解析会话绑定专家，显式传参优先；`MemoryExtractionQueue` 的 `ExtractionRequest` 带 `agent_id` 并透传给抽取函数；`MemorySaveTool/MemorySearchTool` 从 tool context 取 `agent_id` 转发给 `memorize/search_memories`；构造点 `legacy_routes.py`（`producer` 内）+ `hex_routes.py` + `chat_session_lifecycle.py` 从会话绑定注入 `agent_id`；新增 10 个身份归属单测（`backend/tests/memory/test_m3_agent_attribution.py`：抽取透传 / None 保留共享层 / 禁用跳过 / 绑定专家自动归属 / 显式优先 / 向量跨专家过滤 / manager 透传 / 工具透传 ×2）；同步 4 个测试文件的 stale 断言（`test_memory_tool.py` 6 处、`test_async_extractor.py` 4 处 fake 签名、`test_env_memory.py` 2 处 fake store 签名、`test_chat_service_memory.py` 1 处 retrieve 断言）；memory 全域 171 测试 + legacy/hex 路由 32 测试 + lifecycle 25 测试全绿，ruff 通过
- [x] **M3-Task 5** 子代理继承：子会话 `specialist_id` 跟随父会话；测试：subagent 写入归属父专家 — 完成 2026-11-04；`subagent_runner.py` 新增构造参数 `agent_id`（显式记忆归属，`__call__` 的 `agent_id` 是编排角色，命名空间不同）与 `_resolve_memory_agent_id()`（优先级：显式 > 父会话 `resolve_bound_specialist` > 环境工具上下文 > `primary`）；`_bind_child_tool_context()` 用 `dataclasses.replace` 改写**已有**上下文的 `agent_id`，**不凭空构造**上下文（office/file 等按 `ctx.session_id` 授权的工具保持后台路径 fail-closed；无上下文时 memory 工具本就读写拒绝，无跨专家泄漏）；`__call__` 中 bind/reset 置于 try/finally，token 不泄漏到后续调用；新增 7 个单测（父绑定同步上下文 / memory_save 归属父专家 / 显式参数优先 / 无会话回落环境上下文 / 无上下文不造假 / 记忆工具 fail-closed / 结束后上下文复原）；相邻 subagent + orchestration 回归 135 测试全绿，ruff + py38 门禁通过
- [ ] **M3-Task 6** HTTP + 前端：`/memory/list` agent 过滤、`memoryApi`、MemoryBrowser 筛选/徽标/导出过滤；测试：路由参数 + 组件
- [ ] **M3-Task 7** 提升为共享 + 专家删除级联清理；测试：promote 审计、级联删除
- [ ] **M3 验收** E2E：两专家私有记忆互不可见；共享偏好可见；删专家清私有记忆

## 风险评估与依赖

### 风险

1. **旁路泄漏**（最高风险）：`/memory/list`（管理口径不设防）、前端导出、`MemoryAdapter` 向量检索软过滤——各处都必须显式处理 agent 维度；用测试清单逐项覆盖。
2. **hybrid 检索的向量层**：`_vector_add` / `vector_search(soft_filter=True)` 的向量 payload 是否带 agent_id 需在 Task 2 调查确认；若无，向量召回后再按主表行过滤（现 RRF 后有 `is_row_visible` 先例）。
3. **子代理默认 'primary'**：现有子会话若走默认 specialist_id='primary'，专家私有记忆会"泄漏"给 primary 集——Task 5 必须显式覆盖并测试。
4. **FTS 分页**：agent 过滤在主表 JOIN，不影响 FTS 语法；但 `_search_like` 与 `_search_fts` 两条路径都要改，漏一处即泄漏。
5. **双分支**：win7（pydantic v1、py38）需要兼容写法；`MemoryPolicy` 用双兼容模式；迁移脚本纯 SQL 无版本问题。

### 依赖

- M3 依赖 M0 已落地的 `agents.memory_access` 读层封顶（`set_allowed_tiers`）。
- M3 依赖 `sessions.specialist_id`（M0 已加列并索引）。
- M3 依赖迁移机制 v11（runner 已有 v4 模板）。

## 验收测试

- 单元：两专家 memory 表读写隔离矩阵（own/shared/cross × episodic/semantic × fts/like）
- 单元：迁移幂等（空库 / 旧库 / 已迁移库三种起点）
- 集成：`/memory/list?agent_id=` 过滤 + promote 审计 + 专家删除级联
- E2E smoke：写作专家写记忆 → 编码专家检索不到；promote 后双方可见
