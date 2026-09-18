# 项目上下文沉淀（M3：description/instructions + materials + 上下文注入 + 保存回答）

> 日期: 2026-09-15 · 分支: `worktree-sage-ai-workspace-optimization`（基于 `release/win7`，仅 main 验收）
> 前置: [`61-projects-module.md`](./61-projects-module.md)（项目注册表 + workspace binding，本期不重新实现）
> 用户操作指南见 `docs/user-manual/16-project-context.md`

## 1. 定位

项目模块 P1（`61`）提供"项目注册表 + 复用最近会话"。P2（M3）补充项目维度的
**上下文沉淀**——让一个项目的多次会话/多个产物共享同一份"项目记忆"：

- **项目元数据**（description + instructions）：用户对项目的自由描述 + 给 LLM 的指令
- **项目资料**（materials）：用户显式添加的 Markdown 片段（参考文档 / Wiki 摘录 / 历史回答），注入 system prompt
- **保存回答**：把当前会话中助手回答转成资料（保留来源消息元数据），可被下次会话引用
- **上下文注入**：在 chat 主链路把上述三块插入 system prompt，且与上游 SAGE.md/CLAUDE.md 发现链路解耦

约束：

- 项目元数据/资料**不**自动从项目目录读取，避免污染与越权
- 资料内容视为**不可信**（用户输入），注入时显式标注，不得覆盖上层指令
- 优先级固定：应用安全规则（system 头） > 项目概览 > SAGE.md/CLAUDE.md > 全局风格偏好（尾部 dynamic 块）
- 按 `(project_id, content_hash)` 去重，重复添加同内容返回已有行（idempotent）
- 沿用 `session_workspace_bindings` 活跃绑定做归属判定，**不**新增第二份归属数据

## 2. 架构

```
ProjectSection (sidebar)
   ├─ 项目概览面板  (description/instructions textarea + 局部 dirty 检测)
   └─ 资料管理面板  (add via textarea / save-answer / remove / status badge)
        │
        ▼
projectApi (src/shared/api/projectApi.ts)
   ├─ invoke('projects_update')
   ├─ invoke('projects_list_materials')
   ├─ invoke('projects_add_material')
   ├─ invoke('projects_remove_material')
   └─ invoke('projects_save_answer')
        │
        ▼
electron/commands.ts → COMMAND_ROUTES
        │
        ▼
HTTP /api/v1/projects* ─ backend/api/project_routes.py (5 新端点 + PATCH 扩展)
        │                          │
        ▼                          ▼
backend/data/project_repo.py      backend/data/project_material_repo.py
   ├─ update_description()         ├─ add() / get() / list_by_project()
   ├─ update_instructions()        ├─ list_active_for_injection()
   └─ session_stats()              ├─ remove()
                                   └─ MAX_MATERIAL_CONTENT_CHARS=64_000
        │
        ▼  (chat request flow)
backend/chat/project_context.py
   ├─ build_project_metadata_block()  ← description + instructions (8 KB/字段, 16 KB 总)
   └─ build_project_materials_block() ← ready materials (8 KB/条, 16 KB 总)
        │
        ▼
backend/api/legacy_routes.py (chat 主链路装配)
   ├─ description/instructions block 在 SAGE.md/CLAUDE.md 之前
   └─ materials block 在最末，header 标注"不得覆盖上方指令"
```

## 3. 数据模型

### 3.1 `projects` 表扩展（P1 基础上）

```sql
-- 已有: id, path, name, created_at, last_opened_at
ALTER TABLE projects ADD COLUMN description TEXT;     -- 自由描述, ≤ 4 KB
ALTER TABLE projects ADD COLUMN instructions TEXT;    -- 给 LLM 的指令, ≤ 16 KB
```

- 长度上限由前端 `Field(max_length=...)` + 后端 `ProjectUpdateRequest` 双重强制
- PATCH 语义沿用 Pydantic `model_fields_set`：未传入字段保持原值，空 body 为 no-op

### 3.2 `project_materials` 表（DDL in `backend/data/database.py`）

```sql
CREATE TABLE IF NOT EXISTS project_materials (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_message_id TEXT,                  -- 可选,save-answer 场景记录
    content_hash TEXT NOT NULL,              -- SHA-256 hex
    content TEXT NOT NULL,                   -- 单条 ≤ 64 KB
    status TEXT NOT NULL,                    -- pending_index / ready / failed
    wiki_page_path TEXT,
    error_message TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_materials_hash
    ON project_materials(project_id, content_hash);
```

- `content_hash` 复合 UNIQUE INDEX → 重复添加同内容返回已有行（idempotent）
- `status` 三态机：`pending_index`（初始）→ `ready`（索引成功）/ `failed`（索引失败）
- 单条 64 KB 限制（`MAX_MATERIAL_CONTENT_CHARS`），超出抛 `ProjectMaterialContentTooLargeError` → 413

## 4. API 端点

所有 SQL 读写端点统一用 `make_with_db_lock` 装饰，串行化到进程级 `_SQLITE_LOCK`（review HIGH #3 fix，参见 §8）。

| 方法 + 路径 | 说明 | 关键校验 |
|---|---|---|
| `PATCH /api/v1/projects/{id}` | 更新 description/instructions | `model_fields_set` 仅改传入字段 |
| `GET /api/v1/projects/{id}/materials` | 列出资料（含 pending_index/ready/failed） | 404 项目不存在 |
| `POST /api/v1/projects/{id}/materials` | 直接添加（content + optional source_message_id） | content ≤ 64 KB；content_hash 幂等 |
| `DELETE /api/v1/projects/{id}/materials/{material_id}` | 删除单条 | 校验 material 属于该项目 |
| `POST /api/v1/projects/{id}/materials/save-answer` | 从消息保存回答 | (1) message 存在 (2) role == "assistant" (3) message.session_id 当前绑定到该项目 (review HIGH/Security MEDIUM) |

错误码（统一 `_error(status, code, message)` 形态）：

| code | HTTP | 触发条件 |
|---|---|---|
| `project_not_found` | 404 | 项目不存在 |
| `material_not_found` | 404 | 删除不存在的 material 或不属于该项目 |
| `material_too_large` | 413 | content > 64 KB |
| `message_not_found` | 404 | save-answer 引用不存在的 message |
| `message_role_not_savable` | 400 | save-answer 引用 role != "assistant" 的 message |
| `message_project_mismatch` | 403 | message 所属 session 未绑定到该项目 / 绑定到其他项目 |

## 5. 上下文注入

### 5.1 优先级链

```
[system header / 安全规则]
↓ 来自 backend/api/legacy_routes.py chat 主链路
项目概览 (description + instructions)    ← METADATA_HEADER (M3)
SAGE.md / CLAUDE.md / AGENTS.md (向上发现)  ← RENDER_HEADER (M6 既有)
全局风格偏好 / dynamic 块 (尾部)
项目资料 (user-added, 不可信, 不得覆盖上方) ← MATERIALS_HEADER (M3)
```

资料放在最末且 header 显式声明"不得覆盖上方指令"，给模型一个明确的优先级
提示，避免用户上传的 prompt-injection 内容污染指令链。

### 5.2 预算控制（`backend/chat/project_context.py`）

```python
PER_FILE_CHAR_CAP = 8_000   # 单字段/单资料字符上限
TOTAL_CHAR_CAP = 16_000     # description+instructions 或 materials 累计正文上限
```

- 单字段先各自截到 `PER_FILE_CHAR_CAP`
- 然后累计再截一次，超出 `TOTAL_CHAR_CAP` 的部分标 `[截断]`
- materials 列表超出累计预算的资料**排除**（不部分截断），末行注明 `另有 N 条资料超出预算被排除`
- description/instructions 累计超出时，给 description 保留满 `PER_FILE_CHAR_CAP`，剩余给 instructions

### 5.3 隔离保证

- 注入范围严格限定 `project_id`：从 `session_workspace_bindings` 取当前 session
  的项目路径 → 查 `projects` 表拿 `id` → 用该 id 拉 materials
- **不**跨项目导入：即便两个项目同路径（不应出现，但防呆）也按 `project_id` 隔离
- **不**自动读项目目录：用户必须显式添加

## 6. 保存回答（save-answer）

把当前会话中助手回答转成项目资料——典型场景："Sage 帮我梳理了某主题
的回答，希望下次开新会话还能引用"。

### 6.1 前端入口

`ProjectSection.tsx` 资料面板顶部有"保存当前回答"按钮，按钮调用链路：

```
button click
   ↓
electron/commands.ts: projects_save_answer({projectId, messageId})
   ↓
POST /api/v1/projects/{id}/materials/save-answer  {message_id}
   ↓
backend/api/project_routes.py: save_answer_as_project_material
```

`messageId` 来源：从当前 session 最近一条 `role=assistant` 的 message 取出
（前端 hook 维护当前 session 的 message list，UI 触发时取最后一条 assistant）。

### 6.2 服务端校验链（顺序敏感）

1. project 存在 → 404 `project_not_found`
2. message 存在 → 404 `message_not_found`
3. **message.role == "assistant"** → 否则 400 `message_role_not_savable`
   （**security MEDIUM fix**：user-role 内容可能携带 prompt injection 指令）
4. `get_workspace_binding(session_id)` 返回的 binding 必须存在且
   `binding.workspace_path == project.path` → 否则 403 `message_project_mismatch`
5. `ProjectMaterialRepository.add(...)` 写入；
   content_hash 重复 → 返回已有行（同 `(project_id, content_hash)` 幂等）
6. content > 64 KB → 413 `material_too_large`

`source_message_id` 写入资料行 → 后续注入时 header 标注 `(来源消息 xxx)`，
便于追溯"这条资料是从哪条 assistant 回答来的"。

## 7. 前端集成

### 7.1 IPC + API

`src/shared/api/projectApi.ts` 新增 5 方法 + 类型：

```typescript
projects_update(projectId, patch: ProjectUpdatePatch): Promise<Project>
projects_list_materials(projectId): Promise<ProjectMaterial[]>
projects_add_material(projectId, content, sourceMessageId?): Promise<ProjectMaterial>
projects_remove_material(projectId, materialId): Promise<{removed: boolean}>
projects_save_answer(projectId, messageId): Promise<ProjectMaterial>
```

i18n 新增 30 keys（zh.ts + en.ts lockstep）：`materials_*`、`overview_*`、`save_answer_*`。

### 7.2 UI 组件（`src/widgets/sidebar/sections/ProjectSection.tsx`）

- **项目概览面板**：description/instructions 两个 textarea + 局部 dirty 检测 +
  保存按钮（仅 dirty 时可点）。空内容用 placeholder 引导。
- **资料管理面板**：
  - 顶部"保存当前回答"按钮（无当前 assistant 消息时禁用）
  - 添加资料：textarea（前端拦截 > 64 KB） + 添加按钮
  - 资料列表：每条显示 status badge（pending_index 黄 / ready 绿 / failed 红）、
    前 80 字预览、删除按钮；failed 状态显示 error_message 提示
- 受现有 RHF/zod 表单约束影响，textarea 校验通过 maxLength + 手动 trim。

### 7.3 测试

`ProjectSection.test.tsx` 新增 12 个 M3 用例（合计 29 测试）：

- description/instructions 编辑 + 局部 dirty + 保存成功/失败
- materials 列表渲染（pending_index/ready/failed 三态）
- add material：成功、重复（幂等）、超 64 KB 拒绝
- remove material：成功、不存在 404
- save-answer 按钮：禁用状态、点击触发 IPC

## 8. 并发与一致性

### 8.1 review HIGH #3 fix

`backend/api/project_routes.py` 与 `backend/api/artifact_routes.py` 的所有 17 个
SQL 读写端点统一加 `@with_db_lock`：

```python
def with_db_lock(func):
    return make_with_db_lock(globals())(func)

@router.post("/{project_id}/materials")
@with_db_lock
def add_project_material(...) -> ProjectMaterialModel:
    ...
```

`make_with_db_lock` 已扩展支持 async handler（review HIGH #1 修复，见 §8.2），
通过 `asyncio.iscoroutinefunction` 自动选择 sync/async wrapper。两者都通过
`types.FunctionType(...)` 重绑定 `__globals__` 到调用方的模块 globals，
让 FastAPI 仍能解析到原始模块的 Pydantic 模型注解。

### 8.2 review HIGH #1 fix（artifact_routes 关联）

`restore_artifact_version` 持有 `artifact_version_repo._get_lock(artifact_id)`
异步锁后再调 `create_version`，防止 restore 与并发 `apply_edit` 分配到同一
`version_num`。

### 8.3 review HIGH #2 fix（artifact_version_repo 关联）

`create_version` 加 `sqlite3.IntegrityError` 防御性处理：失败时回滚 +
清理已写快照文件 + 转为 `ValueError`，避免 500 污染响应。docstring 显式要求
caller 必须持锁。

## 9. 错误码与可观察性

- 所有错误响应统一 `{"detail": {"code": "...", "message": "..."}}` 形态
  （`_error()` helper）
- 后端 `logger.warning` 记录 material_too_large / message_role_not_savable /
  message_project_mismatch，便于审计
- `project_materials.status=failed` 时存 `error_message` 字段，前端显示重试入口

## 10. 已知边界与未来工作

- **LLM-based 编辑候选**（M2 propose endpoint）待实现：当前版本恢复主路径完整，
  但"选段修改 → 模型生成候选 → 接受/拒绝"链路未闭合
- **项目搜索**：当前清单按 `last_opened_at DESC` 上限 50，跨项目检索未实现
- **资料版本化**：当前 save-answer 每次都是新行（按 hash 去重），但同 message
  修改后再保存不会更新已有行（hash 变了），是否需要"覆盖/新建版本"语义待定
- **跨项目引用**：资料当前严格按 project_id 隔离，未支持"将其他项目的资料
  引用到本项目"——有意保持隔离，避免越权

---

_本节配套测试: backend/tests/api/test_project_routes_m3.py (18 个) +
backend/tests/unit/test_project_material_repo.py (12 个) +
backend/tests/integration/test_project_overview_injection.py (10 个) +
src/widgets/sidebar/sections/ProjectSection.test.tsx (29 个)。_
