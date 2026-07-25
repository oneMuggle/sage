# Office M1–M2 完整收尾设计

> **状态：** 已获用户批准，待规格自审与用户书面复核  
> **日期：** 2026-07-25  
> **目标分支：** `main`  
> **实施分支：** `feat/office-m1-m2-complete`  
> **前置提交：** `main@48eeb1c`（Office M1–M2 chat-read 摘要注入子集）  
> **后续阶段：** M3–M5 Chat-Write 独立 branch/plan；`release/win7` 只通过后续 cherry-pick 同步

## 1. 背景与问题边界

M0 的 Office 存储、读取、导入、安全路径和打包基础已经合并。PR #210/#211 又完成了 `@` Office 文件到 LLM system context 的摘要注入，但它只覆盖了狭义的 chat-read 子集。

当前仍缺少完整 M1–M2 所需的基础层：

- session 与 Workspace 的持久绑定、撤销和查询；
- `workspace_search_files` 的后端/IPC/typed client 链路；
- 不携带本地路径的 `ChatOfficeRef`；
- request-scoped `ToolExecutionContext`；
- `OfficeToolService`、`office_list`、`office_read`；
- Office tool 的动态注册和 legacy Agent 集成；
- Office 页面、Chat 和 AtFileMenu 的单一 Workspace 状态源；
- Electron 与 Python stub 的跨进程关键路径 E2E；
- legacy/hex 两套路由各自创建 attachment executor 的重复实现。

本设计补齐上述 M1–M2 基础，但不实现 M3–M5 的创建、编辑、审批、归档或恢复。

## 2. 目标与非目标

### 2.1 目标

1. 每个 Chat session 最多拥有一个 active Workspace binding，binding 可撤销和重新绑定。
2. 所有 Office 授权均由 `session_id` + binding 决定；LLM 和 tool schema 永不接收自由路径。
3. 用户可在当前 Workspace 搜索、导入并引用 Office 文档，发送 `ChatOfficeRef`。
4. legacy SageAgent 在有有效 binding 时动态暴露 `office_list` 和 `office_read`。
5. Chat、Office、AtFileMenu 读取同一 Workspace context，不再存在 `Office.tsx` 的第二份真相。
6. legacy 与 hex 路由共享一个 attachment executor manager，具有明确、可重复的生命周期。
7. 在真实 FastAPI integration tests 之外，增加 Electron → Python stub 的跨进程 E2E。
8. 新增代码和关键旧代码保持至少 80% coverage，并通过安全审查。

### 2.2 非目标

- `office_create`、`office_edit`、派生版本和 approval stream；
- `office_archive`、`office_restore` 和回收区 UI；
- 把 legacy Chat 迁移到 hex ChatService；
- 删除或修改 `release/win7`；
- 删除 stash、旧 worktree 或远端已合并 feature branch；
- 重写已有 Office reader、generator 或 Electron gateway；
- 为本阶段新增云同步、多人协作或通用文件系统 API。

## 3. 已确认的工程决策

| 决策 | 结果 |
|---|---|
| 实施节奏 | 本轮只完成完整 M1–M2；M3–M5 独立 plan/PR |
| Workspace 真相源 | session-bound Workspace context；不保留双源回退 |
| 主 Chat 路径 | 先接入 legacy `SageAgent.run_loop` |
| hex 路径 | 复用 attachment executor；保留未来 service adapter 边界 |
| tool 参数 | 只允许 `doc_id`、查询过滤和受限 section；不允许 `file_path`/`workspace_path` |
| 文件引用 | `ChatOfficeRef = { docId, docType, filename }`；source path 只在 renderer 导入阶段存在 |
| 绑定变更 | 用户通过原生目录选择器触发；重新绑定不移动、不删除旧文件 |
| 错误策略 | 授权和引用校验 fail-closed；普通无 Office 消息保持 backward-compatible |
| 重试策略 | bind/revoke/search 按 API 语义处理；只读 list/read 可沿用安全重试；无副作用操作不自动重试 |
| 分支 | 从 `main@48eeb1c` 开 `feat/office-m1-m2-complete`；Win7 之后 cherry-pick |
| 清理 | 本轮保留 stash、旧 worktree 和远端 feature branch，只记录状态 |

## 4. 目标架构

```text
Active Chat Session
        │
        ▼
SessionWorkspaceProvider ── workspaceApi ── Electron command map
        │                                      │
        │                                      └─ native selectDirectory
        ▼
Chat / Office / AtFileMenu
        │
        ├─ workspace_search_files → managed Office import → ChatOfficeRef
        │
        └─ chat/stream(session_id, office_refs)
                              │
                              ▼
                    legacy route validation
                              │
                              ▼
                 ToolExecutionContext (ContextVar)
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
          OfficeListTool             OfficeReadTool
                  │                       │
                  └──── OfficeToolService┘
                              │
                  session/doc_id authorization
                              │
                     office_documents + readers
```

Office 领域逻辑只放在 `OfficeToolService`。FastAPI route 负责协议和输入校验，Electron 负责用户动作和 copy/import，React 负责状态与展示，Agent tool wrapper 只负责 schema 和 service 调用。

## 5. Backend 设计

### 5.1 Session Workspace binding

新增 `backend/office/session_workspace.py`，提供：

```python
@dataclass(frozen=True)
class SessionWorkspaceBinding:
    session_id: str
    workspace_path: str
    activated_at: int
    revoked_at: int | None

bind_session_workspace(session_id, workspace_path) -> SessionWorkspaceBinding
get_active_workspace(session_id) -> SessionWorkspaceBinding | None
revoke_session_workspace(session_id) -> None
search_workspace_files(session_id, query, limit) -> list[WorkspaceSearchResult]
```

SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS session_workspace_bindings (
  session_id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  activated_at INTEGER NOT NULL,
  revoked_at INTEGER NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

绑定时验证 session 存在、路径存在且为目录，并通过 `backend/office/path_safety.py` 得到 canonical path。重新绑定以 immutable replacement/upsert 方式写入，不删除原 Workspace 内容。撤销只写 `revoked_at`。

`search_workspace_files` 只返回当前 Workspace 内的文件元数据和 managed `doc_id`。查询长度、返回条数和扩展名均有限制；未托管 Office 文件可以返回 renderer-only 的导入来源信息，但该信息不能进入 Chat payload。

### 5.2 Workspace routes

新增 `backend/api/workspace_routes.py`，挂载在 `/api/v1`：

- `PUT /sessions/{session_id}/workspace`
- `GET /sessions/{session_id}/workspace`
- `DELETE /sessions/{session_id}/workspace`
- `GET /sessions/{session_id}/workspace/files?q=<query>`

路由只调用 binding repository，不直接实现 Office 读写。错误使用稳定 code：`session_not_found`、`workspace_invalid`、`workspace_not_bound`、`workspace_revoked`、`workspace_mismatch`、`document_not_found`。

### 5.3 ChatOfficeRef 和请求验证

Backend 与 shared types 同步：

```python
class ChatOfficeRef(BaseModel):
    doc_id: str
    doc_type: Literal["ppt", "word", "excel"]
    filename: str

class ChatRequest(...):
    office_refs: list[ChatOfficeRef] = Field(default_factory=list)
```

Renderer 使用 camelCase `officeRefs`，现有翻译层负责 snake_case 转换。route 在 LLM 调用前验证每个 ref 的 `doc_id`、类型、归属 Workspace 和未归档状态；任何一个失败则整条 Office 引用请求拒绝。旧 `workspace_path` 字段暂时保留兼容解析，但不能授予 Office 权限；与 active binding 不一致时返回 `workspace_mismatch`。

### 5.4 ToolExecutionContext

新增 `backend/tools/context.py`：

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    stream_id: str
    workspace_path: str
    office_doc_scope: frozenset[str]

current_tool_context() -> ToolExecutionContext | None
```

legacy route 在 `run_loop` 前设置 ContextVar，并在 `finally` 中 reset。没有 active binding 时不暴露 Office tool schema；即使 schema 已暴露，tool 执行时仍重新查询 binding 和 `doc_id` scope。

### 5.5 OfficeToolService 和只读 tools

新增 `backend/office/tool_service.py`：

```text
list(session_id, query, doc_type, limit)
read(session_id, doc_id, section)
```

- `list` 默认隐藏 archived 文档，不返回本地绝对路径；
- `read(summary|head|all)` 返回受限结构化内容，不返回 OOXML bytes；
- 读取前再次执行 session、binding、doc_id、归档状态和路径 containment 检查；
- 结果写入 `office_operation_log` 的摘要字段，不保存完整敏感正文。

新增 `backend/tools/office_tool.py`：

- `OfficeListTool`
- `OfficeReadTool`

两个 wrapper 从 `current_tool_context()` 取得授权上下文，拒绝缺失 context，调用 service，并返回现有 `ToolResult` 格式。注册逻辑支持按 context 动态过滤 Office schema。

### 5.6 Attachment executor 抽取

新增 `backend/chat/executors.py`，提供一个 lazy-created `AttachmentExecutorManager`：

- `resolve(text, workspace)`：使用共享线程池执行现有 `attachment_resolver.process`；
- `shutdown()`：幂等关闭并允许测试环境重新创建；
- FastAPI lifespan 主动调用 shutdown，`atexit` 作为异常退出兜底。

`legacy_routes.py` 和 `hex_routes.py` 删除各自的 `_ATTACHMENT_EXECUTOR`，统一调用该模块。executor 不承担 Office tool 调用，不改变 digest 格式和异常降级语义。

## 6. Frontend 和 Electron 设计

### 6.1 Workspace context

将 `WorkspaceContext` 从 `string | undefined` 扩展为包含状态和动作的不可变 value：

```ts
interface WorkspaceContextValue {
  sessionId: string | null;
  binding: SessionWorkspaceBinding | null;
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  bind: (workspacePath: string) => Promise<void>;
  revoke: () => Promise<void>;
  refresh: () => Promise<void>;
}
```

保留 `useCurrentWorkspace()` 作为兼容 selector，返回 `binding?.workspacePath`。Provider 从当前 session store 读取 session ID；session 切换时取消旧请求、加载新 binding，并清空旧错误。加载失败显示显式错误和 retry，不回退到 `Office.tsx` 本地 state。

`Office.tsx` 删除 `useState<string | null>` workspace source，改为消费 context。`Chat`、`AtFileMenu`、`useOfficeDocuments` 和相关 picker/generator props 统一从该 context 或其 selector 获取。

### 6.2 workspaceApi 和绑定 UI

新增 typed `workspaceApi` 与 Electron command routes：

```ts
bind(sessionId, workspacePath)
get(sessionId)
revoke(sessionId)
search(sessionId, query)
```

目录选择只使用现有 native `selectDirectory`；不新增通用 filesystem IPC。`WorkspaceBindModal` 负责未绑定提示、选择、绑定中、成功、错误和撤销状态。

### 6.3 文件引用

AtFileMenu 的已托管 Office 结果选择后保存 `ChatOfficeRef`，而不是将本地 source path 插入消息。未托管 Office 文件必须先经现有 gateway copy/import，成功获得 `doc_id` 后才能进入 refs。普通文本文件和现有图片/附件流程保持兼容。

## 7. Electron + Python stub E2E

新增测试专用 stdlib Python stub，覆盖：

- `/health`；
- workspace bind/get/revoke/search；
- chat stream 接收 `session_id` 和 `office_refs`，返回可识别的 stub response；
- 将收到的关键请求写入测试临时目录，供 Playwright 断言。

Electron backend launcher 只在 `SAGE_E2E_STUB=1`、非 packaged、非 production 条件下接受测试 entrypoint/python override。生产环境变量和真实 backend 启动路径不变。CI 的 electron-smoke job 显式安装 Python；stub 只依赖 Python 标准库。

核心 E2E：

1. 创建/加载 session；
2. 绑定临时 Workspace；
3. 搜索并导入一个 Office fixture；
4. 通过 Chat 发送包含 `ChatOfficeRef` 的请求；
5. 断言 Python stub 收到 session-scoped ref、没有 source path；
6. 解绑后再次请求，断言 Office 操作被拒绝而普通 Chat 仍可用。

真实 Office reader、路径安全、数据库和 Agent tool 行为仍由 backend unit/integration tests 覆盖，不把业务正确性委托给 stub。

## 8. 错误处理和安全不变量

1. session 不存在返回 404；未绑定/撤销返回稳定 403 code。
2. doc_id 越权统一表现为 not found，不泄露其他 Workspace 的存在性。
3. bind/search 所有外部输入先验证；query 有长度和结果上限。
4. 所有路径使用 component-aware containment，禁止字符串前缀判断。
5. Office 二进制不进入 LLM；tool schema 不包含 path 参数。
6. 错误响应不包含绝对路径；详细上下文只进入受控 server log。
7. ContextVar 必须 reset；并发 Chat session 不能共享授权状态。
8. revoke、session mismatch、tool replay 和 stub override 失败时均 fail-closed。
9. 源文件只复制不移动/删除；本阶段所有 Office 操作均为只读。
10. executor shutdown、DB upsert、provider refresh 和 import cleanup 都必须有异常路径测试。

## 9. TDD 与验收门禁

### 9.1 实施顺序

1. lockfile 版本契约和本 spec；
2. binding schema/repository 单测；
3. workspace routes + Electron command + typed client 集成测试；
4. provider/modal/Office migration Vitest；
5. ChatOfficeRef 全链路和 AtFileMenu 测试；
6. ToolExecutionContext/service/list/read tool 及 legacy Agent 集成测试；
7. shared executor manager 和双 route 回归测试；
8. Python stub + Electron Playwright E2E；
9. 文档更新和旧 M1–M2 plan 状态清理。

每一步遵循 RED → GREEN → REFACTOR；测试先于实现。

### 9.2 必跑检查

- `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest` targeted 与全量；
- Ruff、mypy、import-linter；
- `npm run lint`、`npm run typecheck`、`npm run typecheck:electron`；
- Vitest targeted、全量 coverage，关键新代码覆盖率不低于 80%；
- Electron stub Playwright；
- frontend/electron/backend build；
- security-reviewer、python-reviewer、typescript-reviewer、code-reviewer。

任何 CRITICAL/HIGH finding、覆盖率不足、CI 红灯或安全边界回归都阻止 PR 合并。`release/win7` 只在 main PR 合并后另开 cherry-pick PR，并使用 py38 环境验证。

## 10. 文档和生命周期

- 本 spec 作为完整 M1–M2 的唯一设计基线。
- `2026-07-24-office-m1-m2-chat-read-design.md` 标记为已实现的摘要子集，并链接本 spec。
- `docs/superpowers/plans/2026-07-23-office-m1-m2-chat-read.md` 与 `2026-07-24-office-m1-m2-chat-read.md` 在实施完成后标记 superseded/删除，避免与新 plan 并行产生歧义。
- 新 implementation plan 仅覆盖 M1–M2；完成后把实际 API、Workspace 状态、tool contract、E2E 和安全边界并入 `docs/technical/` 与 `docs/user-manual/`，然后删除 active plan。
- M3–M5 保留独立设计和计划，不在本 spec 中改变其写入/审批范围。

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 旧 Chat 仍发送 workspace_path | 保留字段但不授予权限；绑定缺失时 Office refs/tools fail-closed |
| Provider 与 session store 生命周期错位 | Provider 以 session ID 为 key，切换时取消旧请求并清空 binding state |
| legacy Agent tool registry 是全局结构 | 用 request-scoped context 动态过滤 schema，工具执行再次查 DB |
| 两路 route 的行为漂移 | shared executor 只抽取资源生命周期，不复制 route 逻辑；legacy/hex 各有回归测试 |
| CI 无 conda 环境 | Electron stub 使用 stdlib Python，并在 CI 显式 setup Python |
| 旧计划与新计划重复 | 新 spec 明确 supersede 关系，完成后只保留一个 active plan |
| Win7 Python 3.8 差异 | 本轮 main 先验证；新增 backend 类型和语法保持可 cherry-pick、py38 兼容 |

## 12. 验收标准

- [ ] session 能绑定、读取、重新绑定和撤销 Workspace；
- [ ] 不同 session 不能互读 Workspace 文档；
- [ ] Office 搜索和导入能生成不含 source path 的 ChatOfficeRef；
- [ ] legacy Chat 能在绑定 session 中调用 office_list/read；
- [ ] 未绑定或 revoked session 不暴露 Office tools；
- [ ] Office、Chat、AtFileMenu 使用同一 Workspace context；
- [ ] legacy/hex 共用 executor 且 shutdown 无泄漏；
- [ ] Electron + Python stub E2E 通过；
- [ ] 普通 Chat、非 Office 文件和现有 Office digest 回归通过；
- [ ] backend/frontend/electron coverage 与 CI 门禁通过；
- [ ] 安全、Python、TypeScript 和通用 code review 无阻断项；
- [ ] main 完成后未直接修改或合并 `release/win7`。
