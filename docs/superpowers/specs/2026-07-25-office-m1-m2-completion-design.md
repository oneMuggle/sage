# Office M1–M2 完整收尾设计

> **状态：** 已获用户批准并完成架构自审；implementation plan 已生成，待执行
> **日期：** 2026-07-25
> **实施计划：** [`docs/plans/2026-07-25-office-m1-m2-complete.md`](../../plans/2026-07-25-office-m1-m2-complete.md)
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
2. 所有 Office 授权均由 `session_id` + binding generation 决定；LLM 和 tool schema 永不接收自由路径。
3. 用户可在当前 Workspace 搜索、导入并引用 Office 文档，发送 `ChatOfficeRef`。
4. legacy SageAgent 在有有效 binding 时动态暴露 `office_list` 和 `office_read`。
5. Chat、Office、AtFileMenu 读取同一 Workspace context，不再存在 `Office.tsx` 的第二份真相。
6. legacy 与 hex 路由共享一个 attachment executor manager，具有明确、可重复的生命周期。
7. 在真实 FastAPI integration tests 之外，增加 Electron → Python stub 的跨进程 E2E。
8. 新增代码和关键旧代码保持至少 80% coverage，并通过安全审查。

### 2.2 非目标

- `office_create`、`office_edit`、派生版本和 approval stream；
- `office_archive`、`office_restore`、operation log 和跨轮 Office 操作摘要；
- 把 legacy Chat 迁移到 hex ChatService；
- 为 hex `/chat` 增加完整 Office refs/tools adapter；
- 删除或修改 `release/win7`；
- 删除 stash、旧 worktree 或远端已合并 feature branch；
- 重写已有 Office reader、generator 或 Electron gateway；
- 为本阶段新增云同步、多人协作或通用文件系统 API。

`office_documents.derived_from` 和 `office_documents.archived_at` 已由 M0 migration 存在；M1–M2 只读取 `archived_at` 以隐藏不可读记录，不新增归档行为或 schema。

## 3. 已确认的工程决策

| 决策 | 结果 |
|---|---|
| 实施节奏 | 本轮只完成完整 M1–M2；M3–M5 独立 plan/PR |
| Workspace 真相源 | session-bound Workspace context；不保留双源回退 |
| binding 历史 | 使用 current-state row + 单调递增 generation；不保存 binding 历史 |
| 主 Chat 路径 | 只扩展 `backend.api.legacy_routes.ChatRequest` 和 `/api/v1/chat/stream` |
| hex 路径 | 仅复用 attachment executor；Office refs/tools adapter 留给 M5 |
| tool 参数 | 只允许 `doc_id`、查询过滤和受限 section；不允许 `file_path`/`workspace_path` |
| 文件引用 | `ChatOfficeRef = { docId, docType, filename }`；source path 只在 renderer 导入阶段存在 |
| 绑定变更 | 用户通过原生目录选择器触发；重新绑定不移动、不删除旧文件 |
| 错误策略 | 授权和引用校验 fail-closed；普通无 Office 消息保持 backward-compatible |
| 重试策略 | bind/revoke 不自动重试；search/list/read 可使用受限只读重试 |
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
        ├─ workspace_search_files → existing Office gateway → ChatOfficeRef
        │
        └─ legacy chat/stream(session_id, office_refs)
                              │
                              ▼
             binding + generation + ref validation
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
                 session/generation/doc authorization
                              │
                     office_documents + readers
```

Office 领域逻辑只放在 `OfficeToolService`。FastAPI route 负责协议和输入校验，Electron 负责用户动作和 copy/import，React 负责状态与展示，Agent tool wrapper 只负责 schema 和 service 调用。

## 5. Backend 设计

### 5.1 Session Workspace binding

新增 `backend/office/session_workspace.py`。为兼容后续 Win7 Python 3.8 cherry-pick，backend 公共模型只使用 `typing.Optional/List/FrozenSet`，不使用 PEP 585/604 runtime annotation。

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass(frozen=True)
class SessionWorkspaceBinding:
    session_id: str
    workspace_path: str
    generation: int
    activated_at: int
    revoked_at: Optional[int]

bind_session_workspace(session_id, workspace_path) -> SessionWorkspaceBinding
get_workspace_binding(session_id) -> Optional[SessionWorkspaceBinding]
get_active_workspace(session_id, expected_generation=None) -> Optional[SessionWorkspaceBinding]
revoke_session_workspace(session_id) -> SessionWorkspaceBinding
search_workspace_files(session_id, query, limit) -> List[WorkspaceSearchResult]
```

SQLite 表是 current-state 表，不保存 binding 历史：

```sql
CREATE TABLE IF NOT EXISTS session_workspace_bindings (
  session_id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  generation INTEGER NOT NULL DEFAULT 1,
  activated_at INTEGER NOT NULL,
  revoked_at INTEGER NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

状态规则：

- 首次 bind 创建 generation `1`；
- rebind 原子更新 canonical path、`activated_at`、`revoked_at = NULL`，generation `+1`；
- 首次 revoke 写 `revoked_at` 并 generation `+1`；重复 revoke 幂等返回当前 row；
- generation 变化立即使旧 `ToolExecutionContext`、旧搜索结果和旧 `ChatOfficeRef` 授权失效；
- rebind 不移动或删除旧 Workspace 内容，旧 ref 因 workspace 不匹配而失效。

绑定时验证 session 存在、路径存在且为目录，并通过 `backend.office.storage.validate_workspace` 得到 canonical path。查询文档时必须在一条 repository 查询中同时满足：

```sql
id = :doc_id
AND workspace_path = :active_canonical_workspace
AND archived_at IS NULL
```

禁止先按 `doc_id` 查询再遗漏 Workspace 比较。相同 canonical Workspace 可被多个 session 绑定；每个 session 仍有独立 generation 和 revoke 生命周期。

`search_workspace_files` 的 `query` 最长 200 个 Unicode code points，`limit` 范围 1–50、默认 20。只搜索 active canonical Workspace，支持 `.pptx/.docx/.xlsx` 和现有普通文件结果；symlink/路径别名必须在 canonicalization 后重新做 containment。

### 5.2 Workspace API 与 IPC 契约

新增 `backend/api/workspace_routes.py`，挂载在 `/api/v1`。success body 使用明确 typed object；non-2xx 延续当前 FastAPI 风格：

```json
{"detail":{"code":"workspace_not_bound","message":"当前会话尚未绑定工作区"}}
```

| Electron command | HTTP | Request | 200 response |
|---|---|---|---|
| `workspace_bind` | `PUT /sessions/{session_id}/workspace` | `{"workspace_path":"/synthetic/workspace"}` | `{"binding": SessionWorkspaceBinding}` |
| `workspace_get` | `GET /sessions/{session_id}/workspace` | 无 body | `{"binding": SessionWorkspaceBinding | null}` |
| `workspace_revoke` | `DELETE /sessions/{session_id}/workspace` | 无 body | `{"revoked":true,"generation":2}` |
| `workspace_search_files` | `GET /sessions/{session_id}/workspace/files?q=...&limit=20` | query | `{"results":WorkspaceSearchResult[],"total":N}` |

`GET` 在 session 存在但未绑定时返回 200 + `binding: null`，便于 Provider 正常渲染绑定入口；session 不存在仍返回 404。bind 无效目录返回 400，缺失字段由 Pydantic 返回 422；search 未绑定/已撤销返回 403。

`WorkspaceSearchResult`：

```text
name: string
kind: file | office-ppt | office-word | office-excel
doc_type: ppt | word | excel | null
doc_id: string | null
size_bytes: integer
needs_import: boolean
source_path: string | null  # 仅 renderer 导入阶段；禁止进入 Chat payload
```

`electron/commands.ts::COMMAND_ROUTES` 增加上述四个 command。POST/PUT body 继续由 `electron/invoke.ts::camelToSnakeKeys` 递归转换；GET path builder 显式编码 `sessionId`、`query` 和 `limit`。

### 5.3 Canonical legacy Chat 请求

Renderer 的生产流只调用 `chatApi.chatStream` → Electron `agent_chat_stream` → `POST /api/v1/chat/stream`。因此本阶段只扩展 `backend.api.legacy_routes.ChatRequest`：

```python
from typing import List, Literal

class ChatOfficeRef(BaseModel):
    doc_id: str
    doc_type: Literal["ppt", "word", "excel"]
    filename: str

class ChatRequest(BaseModel):
    session_id: str
    message: str
    workspace_path: Optional[str] = None  # wire compatibility only
    office_refs: List[ChatOfficeRef] = Field(default_factory=list)
    # existing api_key/api_url/model/config fields unchanged
```

`src/shared/api/chatApi.ts::chatStream` 增加第五个可选参数 `officeRefs: readonly ChatOfficeRef[] = []`，并在 `invoke('agent_chat_stream', ...)` 中发送 `officeRefs`。`electron/invoke.ts::camelToSnakeKeys` 将其递归转换为 `office_refs` / `doc_id` / `doc_type`。同步 `chatApi.chat` 和 hex `/chat` 不增加 Office refs；它们不是 renderer 的 Office tool 入口。

route 在启动 producer、保存 user message或调用 LLM 之前完成：

1. 查询 active binding；
2. 若 active binding 存在且 request `workspace_path` 非空，验证它与 canonical binding 一致；无 binding 时忽略该兼容字段，但它不能授权任何 Office 行为；
3. 用 `doc_id + canonical workspace + archived_at IS NULL` 批量验证全部 refs；
4. 捕获 binding generation；
5. 任一 ref 非法则整条请求失败，不创建 stream、不调用 LLM。

普通消息没有 `office_refs` 且没有 active binding 时继续工作。旧 `workspace_path` 不能授予 Office 权限；没有 binding 时不解析 Office attachment digest。

### 5.4 ToolExecutionContext 与 rebind race

新增 `backend/tools/context.py`：

```python
from dataclasses import dataclass
from typing import FrozenSet, Optional

@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    stream_id: str
    binding_generation: int
    office_doc_scope: FrozenSet[str]

current_tool_context() -> Optional[ToolExecutionContext]
```

Context 不保存或接收 request 的 `workspace_path`。route 从 binding repository 取得 generation，在 producer 内围绕 `async for agent.run_loop(...)` set ContextVar，并在 `finally` 中 reset。

`ToolRegistry.get_schemas_for_llm(context=current_tool_context())` 过滤需要 active context 的 Office tools。tool wrapper 执行时调用 `get_active_workspace(session_id, expected_generation)`；generation 不一致、revoke 或 rebind 都返回授权错误。attachment digest 完成后、注入 LLM 前也重新校验 generation，避免 rebind race 将旧 Workspace 内容送入新 turn。

### 5.5 OfficeToolService 和只读 tools

新增 `backend/office/tool_service.py`：

```text
list(session_id, binding_generation, query, doc_type, limit)
read(session_id, binding_generation, doc_id, section)
```

- `list` 调用现有 `backend.office.storage.list_documents`，默认过滤已存在的 `archived_at`；
- `read` 新增/复用 `get_document_in_workspace` 的单 SQL scope 查询；
- `summary|head|all` 返回受限结构化内容，不返回 OOXML bytes 或绝对路径；
- 每次 service 调用都重新验证 binding generation；
- 本阶段不创建 `office_operation_log`，Agent 同轮 tool result 继续使用现有消息链路，跨轮摘要留给 M5。

新增 `backend/tools/office_tool.py`：

- `OfficeListTool`
- `OfficeReadTool`

两个 wrapper 从 `current_tool_context()` 取得授权上下文，拒绝缺失 context，调用 service，并返回 `backend.tools.base.ToolResult`。它们全局注册，但 `backend.tools.registry.ToolRegistry.get_schemas_for_llm` 只在 active context 中向 LLM 暴露；即使模型构造未暴露的 tool call，wrapper 仍 fail-closed。

### 5.6 Attachment executor 抽取

新增 `backend/chat/executors.py`，包含唯一模块级 manager 和三个公开入口：

```text
resolve_attachments(text, workspace) -> awaitable attachment block
shutdown_attachment_executor() -> None
_reset_attachment_executor_for_tests() -> None  # private test hook
```

Manager lazy-create `ThreadPoolExecutor(max_workers=4, thread_name_prefix="attachment-resolver")`，shutdown 时在 lock 内把引用交换为 `None` 后关闭；下一次测试调用可重新创建。`backend/main.py` lifespan 在 shutdown 阶段调用 `shutdown_attachment_executor()`；模块只注册一次 `atexit` fallback。

必须从 `backend/api/legacy_routes.py` 删除 `_ATTACHMENT_EXECUTOR` 及其 `atexit` 注册，从 `backend/api/hex_routes.py` 删除 `_HEX_ATTACHMENT_EXECUTOR` 及其 `atexit` 注册。两路 route 都调用 `resolve_attachments`；digest 格式、50 MiB 上限和 per-mention 降级语义保持不变。

## 6. Frontend 和 Electron 设计

### 6.1 Workspace context 的实际挂载点

将 `src/shared/lib/workspaceContext.tsx` 从 `string | undefined` 扩展为包含状态和动作的 immutable value：

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

新增 `SessionWorkspaceProvider` 并在 `src/app/providers/AppProviders.tsx` 替换当前 `<WorkspaceContextProvider value={undefined}>`。Provider 直接订阅 `src/shared/lib/store.ts::useStore(state => state.currentSessionId)`；Zustand 不需要额外 React provider。`App.tsx` 现有 `loadCurrentSessionId()` 完成后更新 store，SessionWorkspaceProvider 随之加载 binding。

保留：

```ts
useWorkspaceContext(): WorkspaceContextValue
useCurrentWorkspace(): string | undefined
```

`useCurrentWorkspace()` 只返回 `binding?.workspacePath`，保证当前 Chat/AtFileMenu 调用点可渐进迁移。session 切换时 Provider 以 request generation/AbortController 忽略旧响应并清空旧 binding/error。

迁移完成条件：

- 删除 `src/pages/Office.tsx` 的 `const [workspacePath, setWorkspacePath] = useState(...)`；
- Office/Chat/AtFileMenu/`useOfficeDocuments` 只消费 context selector；
- `AppProviders.tsx` 不再传固定 `undefined`；
- typecheck 中不存在双源兼容分支。

### 6.2 workspaceApi 和绑定 UI

新增 `src/shared/api/workspaceApi.ts`，实现 `bind/get/revoke/search` 四个 typed 方法，沿用 `desktopInvoke` 和 `handleApiError`。`WorkspaceBindModal` 负责未绑定提示、调用现有 native `selectDirectory`、绑定中、成功、错误、retry 和撤销状态；不新增通用 filesystem IPC。

Provider 加载失败时保留 `status='error'` 并显示 retry，不回退 Office local state。bind/revoke 是用户动作，不自动重试。

### 6.3 ChatOfficeRef 与现有导入 gateway

AtFileMenu 的已托管 Office 结果选择后保存 `ChatOfficeRef`，不把本地 source path 插入消息。未托管 Office 文件复用既有链路：

```text
preload pickAndImportOfficeFile / importDroppedOfficeFile
→ electron/officeIpc.ts office:pick-and-import / office:import-dropped
→ useOfficeDocuments.ts::readByType
→ officeApi.readPpt/readWord/readExcel
→ backend/api/office_routes.py::_persist_read_summary
→ completeOfficeImport
→ ChatOfficeRef(result.summary.id, doc_type, filename)
```

parse/read 失败继续调用 `discardOfficeImport`，不会生成 ref。普通文本文件和现有图片/附件流程保持兼容。`sourcePath` 只允许存在于未托管搜索结果和 `office:import-dropped` 的用户拖放阶段，永不传给 chatApi、backend ChatRequest 或 LLM。

## 7. Electron + Python stub E2E

### 7.1 Launcher contract

扩展 `electron/backendLauncher.ts::resolveBackendLaunchCommand`，在 dev branch 的 conda 选择之前增加严格测试分支：

```text
if !isPackaged && SAGE_E2E_STUB == "1":
  cmd  = SAGE_E2E_PYTHON
  args = [SAGE_E2E_STUB_PATH, "--port", port]
  reason = "e2e-python-stub"
```

缺少 `SAGE_E2E_PYTHON` 或 `SAGE_E2E_STUB_PATH` 时返回明确的 test configuration error，不回退 conda。packaged 模式完全忽略这三个变量，生产启动仍只走 bundled Python。launcher unit tests覆盖完整变量、缺失变量、packaged ignore 和普通 dev conda 分支。

### 7.2 Stub contract

新增 stdlib Python stub，覆盖：

- `GET /health`；
- workspace bind/get/revoke/search；
- `POST /api/v1/office/{ppt|word|excel}/read`：从 managed path parent 派生 synthetic doc ID，返回现有 read response shape，并存入 stub 内存文档表；
- `POST /api/v1/chat/stream` 与 attach：接收 `session_id`/`office_refs`，返回可识别 NDJSON；
- 将收到的关键请求写入测试临时 JSONL，供 Playwright 断言。

Stub 只用于 IPC/HTTP/stream 契约，不实现真实 OOXML 解析或 tool loop。

### 7.3 核心 E2E

1. 创建/加载 session；
2. 绑定临时 Workspace；
3. 通过现有 drag/drop fixture 触发 `office:import-dropped`；
4. renderer 调 stub Office read endpoint，stub 返回 summary/doc ID；
5. renderer complete import 并生成 `ChatOfficeRef`；
6. 发送 Chat，断言 stub JSONL 含 session-scoped ref 且不含 `source_path`；
7. revoke 后再次发送 Office ref，断言请求被拒绝；普通 Chat 仍可用。

真实 binding repository、Office reader、路径安全、Agent tool 和数据库行为由 backend unit/integration tests 覆盖，不把业务正确性委托给 stub。CI electron-smoke job 显式 setup Python，stub 无第三方依赖。

## 8. 错误处理和安全不变量

1. session 不存在返回 404；未绑定/撤销的 Office 操作返回稳定 403 code。
2. doc_id 越权统一表现为 not found，不泄露其他 Workspace 的存在性。
3. `doc_id + canonical workspace + archived_at IS NULL` 必须同查询验证。
4. rebind/revoke generation 变化使 in-flight Office context 失效；旧 ref 立即失效。
5. bind/search 所有外部输入先验证；query 最长 200、limit 最大 50。
6. 所有路径使用 component-aware containment，禁止字符串前缀判断。
7. Office 二进制不进入 LLM；tool schema 不包含 path 参数。
8. 错误响应不包含绝对路径；详细上下文只进入受控 server log。
9. ContextVar 必须 reset；并发 Chat session 不能共享授权状态。
10. 源文件只复制不移动/删除；本阶段所有 Office tool 操作均为只读。
11. executor shutdown、DB upsert、provider refresh 和 import cleanup 都必须有异常路径测试。
12. E2E override 只在显式测试标志和非 packaged 环境生效。

## 9. TDD 与验收门禁

### 9.1 实施顺序

1. 将 `package-lock.json` 顶层 `version` 和 `packages[""] .version` 从 `0.4.4-alpha.1` 同步为 `package.json` 的 `0.4.5-alpha.28`；保留现有 stash 不变；
2. binding schema/repository/generation/race 单测；
3. workspace routes + `COMMAND_ROUTES` + typed client 集成测试；
4. Provider/modal/Office migration Vitest；
5. legacy `ChatRequest.office_refs`、chatApi 第五参数和 AtFileMenu ref 测试；
6. ToolExecutionContext/service/list/read tool 及 legacy Agent 集成测试；
7. shared executor manager 和双 route 回归测试；
8. Python stub + launcher unit tests + Electron Playwright E2E；
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

任何 CRITICAL/HIGH finding、覆盖率不足、CI 红灯或安全边界回归都阻止 PR 合并。`release/win7` 只在 main PR 合并后另开 cherry-pick PR；所有可移植 backend 模型从一开始使用 Python 3.8/Pydantic v1 可解析的 `typing` 形式，并在后续 Win7 PR 前运行 py38 import/model canary。

## 10. 文档和生命周期

- 本 spec 作为完整 M1–M2 的唯一设计基线。
- `2026-07-24-office-m1-m2-chat-read-design.md` 标记为已实现的摘要子集，并链接本 spec。
- `docs/superpowers/plans/2026-07-23-office-m1-m2-chat-read.md` 与 `2026-07-24-office-m1-m2-chat-read.md` 在实施完成后删除，避免与新 plan 并行产生歧义。
- 新 implementation plan 仅覆盖 M1–M2；完成后把实际 API、Workspace 状态、tool contract、E2E 和安全边界并入 `docs/technical/` 与 `docs/user-manual/`，然后删除 active plan。
- M3–M5 保留独立设计和计划，不在本 spec 中改变其写入/审批范围。

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 旧 Chat 仍发送 workspace_path | 字段只做 mismatch 检测、不授予权限；绑定缺失时 Office refs/tools fail-closed |
| rebind/revoke 与 in-flight turn 竞态 | 单调 generation；route 注入前和每次 tool call 重检 |
| Provider 与 session store 生命周期错位 | Provider 订阅 `useStore.currentSessionId`，切换时取消旧请求并清空 binding state |
| legacy Agent tool registry 是全局结构 | request-scoped context 动态过滤 schema，wrapper/service 双重验证 |
| 两路 route 的 executor 漂移 | 删除两个旧全局 executor，只保留 `backend/chat/executors.py` manager |
| E2E 无法自动操作 native picker | 使用现有 drag/drop gateway；stub 实现真实 HTTP response shape |
| CI 无 conda 环境 | Stub 使用 stdlib Python，并在 CI 显式 setup Python |
| 旧计划与新计划重复 | 新 spec 明确 supersede 关系，完成后只保留一个 active plan |
| Win7 Python 3.8 差异 | 使用 `Optional/List/FrozenSet`，后续 Win7 PR 跑 py38 import/model canary |

## 12. 验收标准

- [ ] session 能绑定、读取、重新绑定和撤销 Workspace；
- [ ] rebind/revoke 使旧 generation、旧 ref 和 in-flight Office tool 失效；
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
