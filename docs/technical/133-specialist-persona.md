# 专家（数字员工）系统 M0–M4

> 分支：`feat/specialist-persona`（切自 release/win7）
> 设计依据：`docs/superpowers/specs/2026-11-03-specialist-persona-design.md`
> 编号说明：win7 上游已占 §129–§131；main 上 §132 已由会话标题生成机制占用，本专题取 §133。

专家（specialist）是 Sage 中可独立配置**提示词、技能、知识源、记忆、模型与权限**的“数字员工”。与普通 agent 的差别不在数据结构，而在运行时接线：选了专家后，提示词、工具白名单、知识检索、记忆归属、模型参数全部按该专家的 profile 生效，切回主助手无残留。

本专题覆盖 M0–M4 五个里程碑的完整实现。

---

## 1. 里程碑总览

| 里程碑            | 交付                                                                                                | 提交锚点                  |
| ----------------- | --------------------------------------------------------------------------------------------------- | ------------------------- |
| M0 接线修复       | `AgentProfile` 真正驱动运行时：提示词分层、模型参数、会话绑定、`memory_access` 读层过滤             | `76a31a104` 之前          |
| M1 专家卡与技能库 | `/specialists` 画廊、创建向导、六段编辑器、技能作用域 fail-closed、专家私有技能目录、`.sage` 包雏形 | `76a31a104`               |
| M2 知识绑定       | `KnowledgeBinding`、路由层检索扇出、RRF 融合、引用深链、无命中拒答                                  | `8a82398ca`               |
| M3 记忆隔离       | `agent_id` 维度、`MemoryPolicy`、身份贯穿、子代理继承、提升为共享、级联删除                         | `87993c2f9`               |
| M4 分发与质量     | 包格式 v2、内置模板库、版本 diff/回滚、黄金任务集评测                                               | `6f1b541e9` / `b8fc1140d` |

---

## 2. 数据模型

### 2.1 `agents` 表扩展字段

`AgentProfile`（`backend/agents/profiles.py`）在通用 agent 字段之外新增：

| 字段                                 | 类型      | 含义                                                        |
| ------------------------------------ | --------- | ----------------------------------------------------------- |
| `role`                               | str       | 专家固定为 `specialist`；主助手为 `primary`                 |
| `source`                             | str       | `user` / `builtin`（模板实例化）/ `imported`（外部包导入）  |
| `persona_ui`                         | JSON      | 头像 emoji、标语、问候语、推荐问题等展示配置                |
| `memory_policy`                      | JSON      | `{write_scope, read_scopes, auto_extract, retention_days}`  |
| `permission_mode`                    | str       | 权限档位；导入时 `full_access` 强制降级为 `workspace_write` |
| `knowledge_bindings`                 | JSON list | `KnowledgeBinding` 列表（见 §5）                            |
| `skills` / `tools` / `memory_access` | JSON list | 技能允许集、工具允许集、记忆读取封顶                        |
| `model_config`                       | JSON      | `{model, temperature, max_tokens}`，为空时回落到全局默认    |
| `max_iterations`                     | int       | 单次任务迭代上限                                            |

`agents.version` 在人设字段变更时自动 +1，作为版本快照的版本号来源。

### 2.2 会话绑定

`sessions.specialist_id TEXT DEFAULT 'primary'`（带索引）。**每会话的当前专家身份从会话绑定解析**，不依赖请求级参数；`resolve_bound_specialist_strict()` 是唯一解析入口。聊天角色选择器（`SessionSpecialistPicker`）写这一列。

### 2.3 版本与评测表（migration v12）

```sql
CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    profile TEXT NOT NULL,                    -- 完整 AgentProfile JSON
    reason TEXT NOT NULL DEFAULT 'update',    -- create / update / rollback
    created_at INTEGER NOT NULL,              -- 毫秒级 Unix 时间戳
    PRIMARY KEY (agent_id, version)
);
CREATE INDEX IF NOT EXISTS idx_agent_versions_agent ON agent_versions(agent_id, version DESC);

CREATE TABLE IF NOT EXISTS agent_eval_runs (
    id TEXT PRIMARY KEY,                      -- uuid4 hex
    agent_id TEXT NOT NULL,
    template_id TEXT,
    created_at INTEGER NOT NULL,              -- 毫秒级 Unix 时间戳
    report TEXT NOT NULL                      -- 评测报告 JSON
);
```

DDL 同时幂等写入 `backend/data/database.py`（与 v11 记忆迁移同一双保险模式）。

### 2.4 专家数据目录

```
~/.sage/specialists/<agent_id>/
├── persona.md        # v2 frontmatter + body=system_prompt
├── avatar.png        # 可选
├── skills/           # 专家私有技能（M1）
├── knowledge/        # 专家私有知识文件（M2）
└── vectors.json      # 专家私有向量库（复用 VectorStore JSON 格式）
```

根路径由 `specialists_root()` 解析，支持 `SAGE_SPECIALISTS_DIR` 环境变量覆盖（测试与「另一台机器」模拟都靠它）。

---

## 3. 提示词分层（M0）

`backend/chat/specialist_prompt_composer.py` 是唯一收敛点：

- `compose_system_prompt(profile, ...)`：完整分层拼装 —— 系统基础段 → 身份/职责/工作方式/输出要求/边界（六段人设）→ 动态上下文（项目、知识检索结果等）→ 专家列表与工具提示。
- `compose_system_prompt_simple(profile)`：无动态上下文的简化版，评测 runner 复用。

`/chat/stream` 在构造请求时从会话绑定解析专家 profile，模型 / temperature / max_tokens 逐项回落到全局设置；`memory_access` 在读取层设置 `allowed_tiers` 封顶（M0 最小执行，M3 的 `MemoryPolicy.read_scopes` 在其上叠加）。

---

## 4. 专家卡与技能作用域（M1）

- 画廊：`/specialists` 页（`src/pages/Specialists.tsx`）+ `SpecialistCard`；创建向导 `SpecialistWizard` 六段人设（身份 / 职责 / 工作方式 / 输出要求 / 边界 / 示例），`persona.md` 与前端解析共用同一格式。
- **技能作用域 fail-closed**：四个入口（聊天工具注入、技能列表、slash 命令、技能执行）统一按 `profile.skills` 允许集过滤；允许集为空 = 不可用任何技能；非法技能名即使被构造出来也无法执行。
- 专家私有技能目录 `~/.sage/specialists/<id>/skills/` 与全局技能库并列被发现，作用域仍受允许集约束。

---

## 5. 知识绑定（M2）

### 5.1 模型

```python
class KnowledgeBinding(BaseModel):
    id: str
    agent_id: str
    source_type: Literal[
        "wiki_project", "zotero_collection", "project_material",
        "workspace_fts", "specialist_private", "sage_docs",
    ]
    source_id: str        # project_id / collection_key / workspace_path
    name: str
    filters: dict = {}
    created_at: int
    class Config:
        extra = "forbid"
```

pydantic v1/v2 双兼容（`class Config` 写法在两代下均可用）。

### 5.2 检索编排

`backend/agents/knowledge_retriever.py` 是**路由层**，不修改现有三层异构向量存储（wiki/attachments JSON VectorStore、project_materials sqlite-vec、rag-service FTS5）：

```
query → 遍历 knowledge_bindings
  ├─ wiki_project       → VectorStore.search(allowed_paths=...)
  ├─ project_material   → ProjectMaterialIndexer.search(source_id, query)
  ├─ specialist_private → ~/.sage/specialists/<id>/vectors.json
  ├─ workspace_fts      → FTS5（待上游接入）
  ├─ sage_docs          → backend/services/sage_docs/search.py (FTS5 + jieba 预分词)
  └─ zotero_collection  → 待上游返回集合元数据后接入
→ 每路 (doc, score) → reciprocal_rank_fusion(k=60) → top-k
```

- 单路 5 秒超时、fail-open；绑定去重；wiki 源打开前校验存储存在与维度（防止 `VectorStore.open()` 建空库）。
- RRF 为纯函数（`backend/agents/rrf.py`），`FusedRank` 保留来源溯源，供引用 chip 反查。

### 5.3 引用与拒答

- 每条结果带 `loc`（page_path + chunk_index / material_id / file_path + line），`sources_extractor` 以 `knowledge` kind 去重；前端「专家知识」分组 chip 可按 source_type 深链跳转（wiki tab / materials tab / toast）。
- **no_hit 拒答**：有绑定但 0 命中且查询非空时，返回 3-tuple `(context_block, sources, no_hit_hint)`，hint 含绑定名与拒答指令并注入动态上下文；检索异常 fail-open 且**不**触发拒答（避免误拦）。
- 可观测：`[SPECIALIST_KNOWLEDGE] span retrieve status=hit|no_hit|error elapsed_ms=...`。

---

## 6. 记忆隔离（M3）

### 6.1 `agent_id` 作为正交维度（migration v11）

```sql
ALTER TABLE memories_episodic ADD COLUMN agent_id TEXT;   -- NULL = 共享
ALTER TABLE memories_semantic ADD COLUMN agent_id TEXT;
CREATE INDEX IF NOT EXISTS idx_episodic_agent ON memories_episodic(agent_id, scope, project_key);
CREATE INDEX IF NOT EXISTS idx_semantic_agent ON memories_semantic(agent_id, scope, project_key);
```

| `agent_id`       | 含义                         | 可见性          |
| ---------------- | ---------------------------- | --------------- |
| `NULL`           | 共享层（历史数据、用户偏好） | 所有专家可见    |
| `'primary'`      | 主助手私有                   | 仅 primary      |
| `'specialist-x'` | 专家私有                     | 仅 specialist-x |

读取语义 = 私有 ∪ 共享：`WHERE (agent_id = :current OR agent_id IS NULL)`；存储层 FTS 与 LIKE 两条路径都加过滤。存量行不回填（NULL 即共享，零迁移风险）。

### 6.2 `MemoryPolicy`

`write_scope=specialist` → 写当前专家；`user` → 写共享；`read_scopes` 不含 `specialist` 时剔除私有行。

### 6.3 身份贯穿

- `ToolExecutionContext.agent_id`（frozen dataclass，默认 `'primary'`，构造点零破坏）。
- `MemoryPort.store/retrieve` 增加可选 `agent_id`；向量召回在 RRF 融合后按 `is_row_visible(current_agent_id=...)` 二次过滤（向量 payload 无 agent 维度）。
- ChatService 自动抽取：显式参数优先，否则 `resolve_bound_specialist(session_id)` 解析会话绑定；`MemoryExtractionQueue` 透传。
- **子代理继承**：`SubagentRunner` 新增构造参数 `agent_id`（与 `__call__` 的编排角色 `agent_id` 是不同命名空间），用 `dataclasses.replace` 改写已有上下文的 `agent_id`，不凭空构造上下文（保持 office/file 工具的后台 fail-closed）。

### 6.4 提升为共享 / 级联删除

- `POST /api/v1/memory/{id}/promote`：同事务内 `UPDATE … SET agent_id = NULL` + 写 `memories_evolution_log` 审计行；审计失败整体回滚；幂等。
- 删除专家：先 `purge_agent_memories(agent_id)`（episodic 软删 `is_valid=0` 保留审计痕迹，semantic 硬删 + FTS 同步，向量表清扫），清理失败返回 500 且**不删除专家本体**（fail-closed）；随后级联删除版本快照与评测记录。
- 管理视图 `/memory/list?agent_id=` 用**精确匹配**（`shared` 哨兵映射 `IS NULL`），与存储层“私有 ∪ 共享”的运行时语义有意不同。

---

## 7. 分发与质量（M4）

### 7.1 专家包格式 v2

`persona.md` frontmatter 升级为完整 profile（body 仍是 `system_prompt`）：

```yaml
format_version: 2
name: 写作专家
tagline: 专业写作助手
description: 专注润色、改写与结构化写作
version: 3
source: user
avatar: '📝'
skills: ['writing', 'polish-*']
knowledge_bindings: [...]
memory_policy: { write_scope: specialist, read_scopes: [specialist, project, user] }
persona_ui: { avatar: '📝', tagline: ..., greeting: ..., suggested_prompts: [...] }
permission_mode: workspace_write
model_config: { model: '', temperature: 0.7, max_tokens: 0 }
max_iterations: 20
memory_access: ['user']
tools: []
enabled: true
```

zip 结构不变：`persona.md` + `avatar.png` + `skills/` + `knowledge/`。

**导入安全钳制**：

- v1 包（只有 `name/version/source`）继续可导入，缺失字段补默认值。
- `role` 强制 `specialist`；`source` 强制 `imported`；`permission_mode == full_access` 降级为 `workspace_write`。
- `skills` / `tools` / `memory_access` 只接受字符串数组并去重限量。
- `knowledge_bindings` 仅保留 `specialist_private` 并重绑到新 `agent_id`，其余计入响应 `dropped_bindings`（跨机器不存在对应项目/集合）。
- 导出单文件失败 fail-safe（跳过该文件，包仍可生成）。

### 7.2 内置模板库

- 6 套模板：Sage 向导 `sage-guide`（首位、固定 id 幂等实例化）、写作 `writing`、研究 `research`、编码 `coding`、演示 `presentation`、Office `office`。每套是一个目录（目录名 = `template_id`），内含与用户包同格式的 v2 `persona.md` + 私有技能——**单一真相源，不另立模板 DSL**。
- `backend/services/specialist_templates.py`：`list_templates()` 返回元数据（id/name/tagline/avatar/描述/技能数），不暴露完整提示词；`instantiate_template(template_id)` 复用导入管线物化函数，生成 `agent_id = specialist-<template_id>-<6hex>`、`source=builtin`，失败整体回滚（不写半成品 agents 行）。
- `_TEMPLATES_DIR` 为模块相对路径，PyInstaller 打包需 `datas` 显式包含（见 §9）。

### 7.3 版本 diff / 回滚

- 快照时机：创建时存 v1；每次 PATCH 前幂等存「当前版本」，更新后版本号变化再存新版本；回滚后存新版本（`reason=rollback`）。
- 保留策略：每专家最近 50 个版本，超出按 version 升序删除。
- API：`GET /agents/{id}/versions`、`GET /agents/{id}/versions/{version}`、`GET /agents/{id}/versions/diff?from=&to=`（白名单字段字段级 diff）、`POST /agents/{id}/rollback`（恢复快照并 `version+1`）。
- 前端 `VersionHistoryDialog`：版本列表 + 字段 diff + 回滚二次确认。

### 7.4 黄金任务集评测

- `backend/services/golden_tasks.json`：5 模板 × 2 任务 = 10 条，字段 `id / template_id / topic / prompt / checks`。
- 检查器全部确定性：`keywords_all / keywords_any / forbidden / refusal / regex / max_chars`；非法 kind 保守判失败，不抛异常污染整体报告。
- Runner 可注入：`async (profile, task) -> {"output", "tool_calls", "tokens"}`。**测试与 CI 全部注入假 runner，不发真实 LLM 请求**；生产 `default_llm_runner` 复用压缩摘要的 LLM 装配，单任务失败记 `error` 不中断其余任务。
- 路由：`GET /specialists/golden-tasks`（目录）、`POST /specialists/{agent_id}/eval`（可选 `task_ids` 子集）。结果写 `agent_eval_runs`，返回 `run_id` + 报告（总通过率、按模板聚合、逐任务检查明细、tokens、起止时间）。
- 仅模板实例化专家（`template_id_from_agent_id` 可解析）支持评测；非模板专家返回 400 `agent_not_template_instantiated`。
- 前端 `SpecialistEvalDialog`：打开即加载任务目录，展示覆盖率、运行评测、逐任务检查明细。

---

## 8. API 一览

| 方法   | 路径                                                      | 用途                                                |
| ------ | --------------------------------------------------------- | --------------------------------------------------- |
| GET    | `/api/v1/specialists/templates`                           | 列出内置模板元数据                                  |
| POST   | `/api/v1/specialists/templates/{template_id}/instantiate` | 一键创建专家（201）                                 |
| GET    | `/api/v1/specialists/{agent_id}/export`                   | 导出 `.sage` zip 字节流                             |
| POST   | `/api/v1/specialists/import`                              | multipart 导入 zip → `{id, name, dropped_bindings}` |
| GET    | `/api/v1/specialists/golden-tasks`                        | 黄金任务目录（10 任务 / 5 模板）                    |
| POST   | `/api/v1/specialists/{agent_id}/eval`                     | 运行评测（可选 `task_ids`）                         |
| GET    | `/api/v1/specialists/{agent_id}/knowledge`                | 知识绑定列表                                        |
| POST   | `/api/v1/specialists/{agent_id}/knowledge`                | 新增绑定（201）                                     |
| DELETE | `/api/v1/specialists/{agent_id}/knowledge/{binding_id}`   | 删除绑定（204）                                     |
| GET    | `/api/v1/agents/{agent_id}/versions`                      | 版本列表（倒序）                                    |
| GET    | `/api/v1/agents/{agent_id}/versions/{version}`            | 完整快照                                            |
| GET    | `/api/v1/agents/{agent_id}/versions/diff?from=&to=`       | 字段级 diff                                         |
| POST   | `/api/v1/agents/{agent_id}/rollback`                      | 回滚（body `{version}`）                            |
| GET    | `/api/v1/memory/list?agent_id=`                           | 记忆管理视图（精确匹配，`shared` 哨兵）             |
| POST   | `/api/v1/memory/{memory_id}/promote`                      | 提升为共享                                          |

路由路径均以 `/api/v1` 开头；Electron 桥接要求带 body 的路由提供显式 `body` 函数剥离路径参数键（pydantic `extra="forbid"` 否则 422）。

---

## 9. 双分支与打包

- 本特性整体从 release/win7 切出，**必须整体合入**，不可单挑 M4 cherry-pick。
- 兼容约束：Python 3.8 / pydantic 1.x（win7）与 3.10 / pydantic 2（主分支）双环境全绿；`scripts/check_py38_compat.py` 静态门禁 0 违规。新代码统一 `typing.List/Dict/Optional`、`class Config: extra="forbid"`、避免 `X | Y` 与 `list[...]`。
- PyInstaller（`scripts/backend.spec`）：

```python
datas = [
    (str(BACKEND_DIR / "services" / "specialist_templates"), "backend/services/specialist_templates"),
    (str(BACKEND_DIR / "services" / "golden_tasks.json"), "backend/services"),
    # sage-guide 知识源：docs/user-manual 全量 + 技术手册白名单 13 篇
    # 白名单单一源头：backend/services/sage_docs/paths.py::TECHNICAL_WHITELIST
    (str(DOCS_DIR / "user-manual"), "docs/user-manual"),
] + [(str(DOCS_DIR / "technical" / name), "docs/technical") for name in TECHNICAL_WHITELIST]
```

缺少这三项会导致发行包里模板枚举/评测失败或向导"失明"。Windows 安装包走整目录复制，天然包含模板与 golden_tasks；docs 走 `extraResources` 同步策略（与 `electron-builder.yml` 的 `technical/*` 列表保持一致）。

---

## 10. 前端组件

| 组件                          | 位置                       | 职责                                           |
| ----------------------------- | -------------------------- | ---------------------------------------------- |
| `Specialists.tsx`             | `src/pages/`               | 画廊页；顶部「从模板创建」；空态内嵌模板网格   |
| `SpecialistCard.tsx`          | `src/widgets/specialists/` | 专家卡 + 动作（编辑/知识/版本/评测/导出/删除） |
| `SpecialistWizard.tsx`        | 同上                       | 创建向导（六段人设 + 能力与权限）              |
| `toolCapabilities.ts`         | `src/entities/specialist/` | 能力包定义与工具选择派生函数（§12）            |
| `ToolAllowlistEditor.tsx`     | `src/widgets/agents/`      | 共享工具白名单编辑器（`/agents` 与向导复用）  |
| `TemplateGalleryDialog.tsx`   | 同上                       | 模板画廊一键创建                               |
| `VersionHistoryDialog.tsx`    | 同上                       | 版本列表 / diff / 回滚                         |
| `SpecialistEvalDialog.tsx`    | 同上                       | 黄金任务集评测                                 |
| `KnowledgeBindingsEditor.tsx` | 同上                       | 知识绑定编辑                                   |
| `SessionSpecialistPicker.tsx` | `src/widgets/chat/`        | 聊天头部专家选择器                             |

API 层：`src/shared/api/specialistApi.ts`（模板/评测/导入导出）、`specialistKnowledgeApi.ts`、`agentApi`（版本/回滚）。

---

## 11. 测试矩阵

| 层       | 文件                                                                                                                      | 覆盖                                             |
| -------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 包格式   | `backend/tests/unit/test_specialist_package_v2.py`                                                                        | 全字段往返、v1 向后兼容、导入钳制                |
| 模板     | `backend/tests/unit/test_specialist_templates.py`                                                                         | 列表、实例化、失败回滚                           |
| 版本     | `backend/tests/unit/data_repo/test_agent_version_repo.py` + `backend/tests/unit/api/test_legacy_agent_versions_routes.py` | 快照/列表/diff/回滚/裁剪/级联                    |
| 评测     | `backend/tests/unit/test_specialist_golden_eval.py` + `backend/tests/unit/api/test_specialist_eval_routes.py`             | 六种检查器、聚合、假 runner 路由、落库           |
| 知识     | `backend/tests/unit/test_knowledge_retriever.py` 等                                                                       | RRF、路由扇出、no_hit 拒答                       |
| 记忆     | `backend/tests/memory/test_m3_*.py`                                                                                       | 隔离矩阵、promote、级联                          |
| 验收 E2E | `backend/tests/e2e/test_m4_distribution_acceptance.py`                                                                    | 模板建写作专家；导出→另一目录导入全字段一致      |
| 记忆 E2E | `backend/tests/e2e/test_m3_memory_isolation_acceptance.py`                                                                | 两专家互不可见、共享可见、删除级联               |
| 前端     | `src/widgets/specialists/__tests__/*`                                                                                     | 三个 Dialog + KnowledgeBindingsEditor（24 测试） |
| 工具选择 | `src/entities/specialist/__tests__/toolCapabilities.test.ts`、`src/widgets/agents/__tests__/toolAllowlist.test.ts`、`ToolAllowlistEditor.test.tsx`、`SpecialistWizard.test.tsx`、`src/pages/__tests__/SpecialistDetail.test.tsx` | 能力包推导、白名单编辑器、向导保存 payload、详情页展示 |
| 防漂移   | `backend/tests/unit/test_specialist_tool_packs_drift.py`                                                                  | 能力包工具名 ⊆ 内置工具清单（117 项）            |

双环境验证（py310 + py38）M4 相关 117 测试 × 2 全绿；py38 静态门禁 0 违规；`tsc` + `npm run build` 通过。

---

## 12. 工具白名单与能力包

### 12.1 `tools` 的三态语义

`profile.tools` 同时被**schema 暴露**（`backend/tools/registry.py` 的 `get_schemas_for_llm`）与**调用分发**（`backend/core/legacy/agent.py` 的「工具未对当前 Agent 开放」拒绝分支）使用，三种取值语义不同：

| 取值    | 含义                                     |
| ------- | ---------------------------------------- |
| `None`  | 历史遗留：不限制（仅主助手等旧档案使用） |
| `[]`    | **不授权任何工具**（纯对话专家）         |
| `[...]` | 仅允许列表内的工具名                     |

`[]` 是安全正向的显式语义，不会回落到「全部允许」。因此向导不能把 `[]` 当作未填写的默认值静默写入 —— 新建专家必须给出显式的工具集合，历史 `tools: []` 的专家在编辑时也保持纯对话，直到用户主动勾选能力包。

### 12.2 能力包（前端静态映射）

`src/entities/specialist/toolCapabilities.ts` 声明 14 个能力包：

```ts
interface ToolCapabilityPack {
  id: string;                              // 'file-read'
  label: string;                           // '文件读取与检索'
  description: string;                     // 一句话说明
  tools: readonly string[];                // 与后端工具名精确一致
  requiresMode: SpecialistPermissionMode;  // 包内工具实际可用所需的最低模式
}
```

| 能力包                                                                          | `requiresMode`    | 说明                           |
| ------------------------------------------------------------------------------- | ----------------- | ------------------------------ |
| 文件读取与检索 / 记忆与会话检索                                                 | `read_only`       | 只读工具，任意权限模式可用     |
| 文件编辑 / 网络 / 办公 / Git / 多模态 / 设计                                    | `workspace_write` | 写入类，`read_only` 下被拒绝   |
| 命令执行 / 浏览器 / Sage 配置 / 定时任务 / 技能·子代理·待办 / 插件              | `full_access`     | 执行或自改配置类，`prompt` 下逐次审批 |

`plugins` 包以 `plugin__*` 通配表达。`office_delete` 归入「办公」但暂不打包（卸载类操作单独控制，避免整包勾选时被一并授权）。

### 12.3 派生函数

纯函数，供向导、预览与详情页复用：

| 函数                                  | 用途                                            |
| ------------------------------------- | ----------------------------------------------- |
| `packSelectionState(tools, pack)`     | `'all' \| 'partial' \| 'none'`，驱动复选框中间态 |
| `togglePackInTools(tools, pack, on)`  | 加入/移除**该包自己的**工具名，保留手工条目     |
| `describeToolSelection(tools)`        | 完全覆盖的包 / 部分覆盖的包 / 未归类工具名      |
| `describeModeGate(mode, pack)`        | 当前模式下的拒绝或审批提示；`null` 表示无门槛   |
| `highestRequiredMode(packs)`          | 所选包中最高门槛，供汇总提示使用                |

`defaultSpecialistTools()` = `file-read` + `network` + `memory` 三包并集，是新建专家的默认值（只读、开箱可用）。

### 12.4 向导第 3 步与保存

`SpecialistWizard` 的四步为：基本信息 → 人设六段 → 能力与权限 → 预览。第 3 步顺序是**权限模式 → 工具能力 → 技能**：

- 显式二选一：「使用下方能力」/「不使用任何工具（纯对话）」。选择纯对话时能力包网格隐藏，保存 `tools: []`。
- 能力包复选框网格：勾选加入整包工具，取消只移除该包工具名；部分覆盖显示中间态。
- 权限模式门槛提示（`specialist-wizard-mode-gate-deny` / `-approval`）只是**提示**，不阻断选择 —— 最终是否放行由权限引擎（`backend/tools/permissions.py`）裁决，保持单一真相源。
- 高级折叠区复用 `ToolAllowlistEditor`（与 `/agents` 页同一组件），支持逐项白名单、运行中插件工具与未发布条目。
- 创建与更新 payload 都写 `tools`；编辑时若原来 `tools` 非空，按原列表回填，不追加默认包。

### 12.5 只读展示

详情页 Tab「能力」（原「技能」）在技能 chips 之下增加「工具能力」卡片：按能力包展示完全覆盖 / 部分覆盖状态，未归类工具名原样列出；`tools` 为空时显示「纯对话专家」警告。预览步骤的摘要卡片与详情页共用 `describeToolSelection`，文案一致。

### 12.6 防漂移

`backend/tests/unit/test_specialist_tool_packs_drift.py` 断言能力包内每个工具名都存在于后端内置工具清单（`_EXPECTED_ONLINE`，117 项）。工具重命名或删除时该测试变红，强制前端映射同步更新。
