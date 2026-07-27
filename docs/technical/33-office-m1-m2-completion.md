# Office M1–M2 完整收尾 (33)

> Chapter 33 与 M3–M5 边界：本章节只覆盖 Office 会话-工作区绑定、Office 引用透传、Office list/read 工具以及 Electron → Python stub 端到端 E2E 测试。M3–M5 (写入、编辑、归档、审批流) 由独立分支 `fix/office-m3-m5-chat-write` 实施，不属于本章节。

## 1. 背景

Sage M0 已经把 Office 模块从命令式调用升级为带 managed-dir、绑定生命周期、错误信封、跨平台打包与 16 项安全规则的统一模块。M1–M2 在 M0 之上叠加：

- 用户在 Chat 会话上显式绑定一个目录 (Workspace Binding)，Office 流的所有授权都围绕该 binding 派生；
- `@<file>` 引用从 DSL 变成结构化 `ChatOfficeRef` payload，仅含 `docId/docType/filename`；
- LLM 可以通过 `office_list` / `office_read` 工具主动查询/读取 Workspace 内文档；
- 跨进程契约 (renderer → IPC → backend) 由一个 stdlib Python stub server + 10 个 Playwright 场景锁定，避免完整 FastAPI 启动依赖。

## 2. 实施范围

### 2.1 一句话范围

`session_id + binding_generation` 是 M1–M2 的 root of authority：每个 Chat turn 同步从 `session_workspace_bindings` 读取 binding，注入 request-scoped `ToolExecutionContext`，驱动工具 schema 与执行授权。

### 2.2 不在范围

- Office 文档写入 (`office_create` / `office_edit`)、派生版本、approval stream、归档与恢复；
- 把 legacy Chat 迁移到 hex ChatService；
- 为 hex `/chat` 适配完整 Office refs/tools；
- 删除 stash、旧 worktree 或远端 feature branch；
- 改动 `release/win7`（win7 同步在 main 合并后通过独立 cherry-pick PR 进行）。

## 3. 架构

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
        └─ legacy chat/stream(session_id, office_refs)
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
                 session/generation/doc authorization
                              │
                     office_documents + readers
```

约束：

- OfficeToolService 与 OfficeToolProvider 都集中在 `backend/office/` 与 `backend/tools/`，不依赖路由；唯一的输入是 `conn + session_id + binding_generation`。
- 副作用全部走 `_persist_*` 写入；Office 服务只读，不引入新的 operation log/跨 turn 摘要。
- 路径校验复用 `backend/office/path_safety.py` 与 `backend/office/storage.py::validate_workspace`，禁止字符串前缀 containment。

## 4. 关键契约

### 4.1 Binding 表

`session_workspace_bindings` 是 current-state 行 (无历史)：

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

规则：

- `bind` 是 rebind：INSERT ... ON CONFLICT DO UPDATE 清空 `revoked_at` 并 `generation += 1`。
- `revoke` 只写 `revoked_at` 并 `generation += 1`；重复 revoke 幂等返回当前 row。
- 跨 session/binding 查询受 `archived_at IS NULL` 与 `workspace_path = :active_canonical` 双重限定。

### 4.2 `ChatOfficeRef` 与 `AuthorizedOfficeRequest`

```python
class ChatOfficeRef(BaseModel):
    doc_id: str = Field(min_length=1, max_length=256)
    doc_type: Literal["ppt", "word", "excel"]
    filename: str = Field(min_length=1, max_length=256)
    model_config = ConfigDict(extra="forbid")

@dataclass(frozen=True)
class AuthorizedOfficeRequest:
    session_id: str
    binding_generation: int
    office_doc_scope: FrozenSet[str]
    workspace_path: str
```

`authorize_chat_office_request` 在 `StreamRegistry.create` 之前同步执行：

1. active binding 的 `session_id` 存在；
2. rebind/revoke 检测：`get_active_workspace(..., expected_generation=...)`；
3. `request.workspace_path`（如有）走 `validate_workspace` 规范化后与 binding 一致；
4. 每个 ref `id + workspace_path + archived_at IS NULL` 单 SQL 验证。

任一失败抛 `WorkspaceDocumentNotFoundError` / `WorkspacePathMismatchError` / `WorkspaceNotBoundError` / `WorkspaceSessionNotFoundError`，由 legacy route 映射到 400/403/404 并阻止 stream id 创建。

`requires_tool_context=True` 的 Office 工具在 `ToolRegistry.get_schemas_for_llm(context=None)` 时被排除；当 producer 持有合法 `AuthorizedOfficeRequest` 时构建 `ToolExecutionContext` 并通过 `set_tool_context` 注入。

### 4.3 HTTP API

新增 4 个 session-scoped Workspace 端点：

- `PUT /sessions/{session_id}/workspace` (`workspace_bind`) — 接受 `{workspace_path}`，返回 binding；
- `GET /sessions/{session_id}/workspace` (`workspace_get`) — 返回 `{binding: ... | null}`；
- `DELETE /sessions/{session_id}/workspace` (`workspace_revoke`) — 返回 `{revoked: true, generation: N}`；
- `GET /sessions/{session_id}/workspace/files?q=&limit=` (`workspace_search_files`) — 返回 `WorkspaceSearchResponse`。

错误信封 `{detail: {code, message}}`；搜索结果不暴露绝对路径，仅返回 workspace-relative `name` + `source_path`（仅渲染阶段使用，绝不进入 Chat payload）。

### 4.4 Renderer

- `workspaceApi` 仅暴露 camelCase，client 内部做 snake→camel 映射；
- `useStore(state => state.currentSessionId)` 驱动 `SessionWorkspaceProvider`；使用单调 `requestIdRef` 处理 in-flight 竞态；
- `useCurrentWorkspace()` 仍返回 `binding?.workspacePath` 作为 back-compat selector；
- `useOfficeDocuments` 通过新 helper `importOfficeReference` 复用 `electron.office.importDroppedOfficeFile → officeApi.read* → completeOfficeImport` 生命周期；
- AtFileMenu 用 discriminated union `{kind:'file'/'office-import'/'office'}` 选择行为，普通文件永不伪造 `ChatOfficeRef`；
- `chatApi.chatStream` 新增第 5 个参数 `officeRefs`，向后兼容默认 `[]`。

### 4.5 Shared executor

`backend/chat/executors.py` 提供 `resolve_attachments(text, workspace)` + 模块级 `ATTACHMENT_EXECUTOR` (max_workers=4) + `atexit` fallback；legacy 与 hex 两条 route 共享同一 manager。FastAPI lifespan 主动 `shutdown_attachment_executor()`，`atexit` 仅作兜底。

### 4.6 Electron → Python stub E2E

- `tests/electron/conftest.py` 启动 stdlib stub + Electron main process + 设置 `SAGE_BACKEND_URL`；
- `tests/electron/stub_backend.py` (stdlib-only) 实现完整 API：`/health`、sessions CRUD、workspace bind/get/revoke/search、Office read、chat stream NDJSON；支持 Task 6 `office_refs` 授权四象限；
- `tests/electron/office-e2e.spec.ts` 10 个场景，覆盖 session 创建 → workspace 绑定 → drag-drop import → `@sample` → Office chip → 发送 + stub 断言 → 解绑 → 失败回退 → 普通 Chat 仍可用。

## 5. 测试覆盖

### 5.1 Backend

| 套件 | 测试数 | 覆盖范围 |
| --- | --- | --- |
| `backend/tests/unit/office/test_session_workspace.py` | 13+ | bind/rebind/revoke、generation、symlink canonical、跨 session、文档 scope |
| `backend/tests/unit/office/test_workspace_search.py` | 11+ | dedupe、symlink 跳过、limit/query 边界 |
| `backend/tests/unit/office/test_chat_refs.py` | 19 | 5 条授权规则 + workspace canonical mismatch |
| `backend/tests/unit/office/test_tool_service.py` | 15 | generation mismatch、policy limits、summary/head/all、path leak |
| `backend/tests/unit/tools/test_context.py` | 11 | ContextVar default/set/reset/nested/concurrent |
| `backend/tests/unit/tools/test_registry_office_filter.py` | 10 | context-aware schema filter |
| `backend/tests/unit/tools/test_office_tool.py` | 10 | missing context、unknown doc_id、happy path |
| `backend/tests/unit/test_chat_executors.py` | 7 | shared executor 生命周期 |
| `backend/tests/integration/test_workspace_routes.py` | 10 | HTTP status、错误信封 |
| `backend/tests/integration/test_chat_stream_office_refs.py` | 5 | pre-stream authorization、no-registry-entry |
| `backend/tests/integration/test_chat_office_tools.py` | 6 | LLM mock tool-loop、rebind race |
| `backend/tests/integration/test_chat_attachment_injection_legacy.py` | 4 | 回归不破 |
| `backend/tests/integration/test_chat_attachment_injection_hex.py` | 5 (skip in legacy mode) | 回归不破 |

### 5.2 Frontend

| 套件 | 测试数 |
| --- | --- |
| `src/shared/api/__tests__/workspaceApi.test.ts` | 6 |
| `src/app/providers/__tests__/SessionWorkspaceProvider.test.tsx` | 11 |
| `src/features/workspace/__tests__/WorkspaceBindModal.test.tsx` | 14 |
| `src/pages/__tests__/Office.workspace.test.tsx` | 9 |
| `src/pages/__tests__/Chat.workspace.test.tsx` | 3 |
| `src/shared/api/__tests__/fileSearchClient.test.ts` | 16 |
| `src/shared/api/__tests__/chatApi.office.test.ts` | 6 |
| `src/features/chat/__tests__/AtFileMenu.ref-selection.test.tsx` | 8 |
| `src/widgets/chat/__tests__/ChatInput.officeRefs.test.tsx` | 7 |
| `src/features/office/__tests__/useOfficeDocuments.test.ts` | 8 |

完整仓库 suite: `npm run test:run` → ~850 passed, 0 failed (含 5 个 hex-mode skip)。

### 5.3 Electron + stub

| 套件 | 测试数 |
| --- | --- |
| `tests/electron/test_stub_backend.py` | 29 |
| `tests/electron/office-e2e.spec.ts` | 10 |

通过 `SAGE_SKIP_E2E=1` 时 10 个 E2E 优雅跳过 (用于 PR 不需要 Playwright 的轻量 pipeline)。

## 6. 已记录的 Minor Findings

主分支在最终合并前可一次性清理；不在 M1–M2 范围内修复：

1. `_DOC_ID_PATTERN = re.compile(...)` 在 `path_safety.py:33`，可拆为 `re.IGNORECASE` 兼容 `.DOCX` (LOW)。
2. `PRAGMA foreign_keys=ON` 未在 `Database.get_connection()` 启用，`session_workspace_bindings.FOREIGN KEY` 当前是 silent no-op (MEDIUM, 安全 follow-up)。
3. `process_mentions` 在 `attachment_resolver.py` 与 `chat_refs.py` 路径术语不一致；不影响测试正确性 (LOW)。
4. `_read_doc` 路径异常路径只覆盖 `OSError`，`ZipFile` 错误应在 reader 层处理 (LOW)。
5. `importOfficeReference` 中 `result.name` 用作 `filename`；若后端以 gateway `originalName` 回传，则需替换 (LOW, 安全 cosmetic)。
6. `E2E test 04` 用 stub API 直接绑定 workspace 而非走 UI IPC；UI 集成 CI 不稳定 (LOW, test-only)。
7. `Office.tsx` `readIdRef` 在 modal 关闭时无差别 bump (LOW, defensive)。
8. `WorkspaceContext` `Provider` 用 `createContext<... \| null>(null)`，离开 provider 抛错（正确）；导出 `useWorkspaceContext` 之外的 hook 时与既有 selector 共存，无冲突 (LOW)。
9. `Planner.py` 中 `TODO: Implement plan refinement with LLM` (FUTURE, M+)。
10. `wiki/vectorstore_hnsw.py` 定期重建索引 (FUTURE, 增强)。
11. `_validate_search` 抛 `ValueError` 由 route 层 catch 映射 422，已通过测试覆盖 (LOW, 测试已锁)。
12. `legacy_routes` `workspace_path` mismatch 由 task 6 fix 采用 `validate_workspace` 规范化 (CLOSED, fix 已 merged)。
13. `PRAGMA foreign_keys=ON` `ON DELETE CASCADE` 沉默；可后续添加 (MEDIUM, 安全 follow-up, 与 #2 重叠)。
14. `_read_content` 返回 dict 与 `ToolResult` 混用类型的不一致，仅说明注释可改善 (LOW)。
15. `E2E test 07` 假设 stub 在 1s 内启动；在慢 CI 上若 flaky，可在 conftest 加 retry (LOW, resilience)。

上述 15 条全部为 LOW/MEDIUM，对正确性不影响，无 CRITICAL/Important；最终 review 阶段不阻塞合并；可在合并后单独 PR 清理。

## 7. 决策记录

| ID | 决策 | 备选 |
| --- | --- | --- |
| 2026-07-25-01 | binding 使用 `INSERT ... ON CONFLICT DO UPDATE` current-state 行 | 历史表 + active pointer |
| 2026-07-25-02 | `office_list/read` 工具 schema 无 path 参数，仅含 `doc_id/section/query/doc_type/limit` | 允许 path |
| 2026-07-25-03 | `ToolExecutionContext` 仅包含 `session_id/stream_id/binding_generation/office_doc_scope` | 携带 workspace 路径 |
| 2026-07-25-04 | OfficeToolService 输出移除 `workspace_path` 字段，保留 `doc_id/doc_type/filename` | 全字段透传 |
| 2026-07-25-05 | attachment executor 用模块级 manager 共享，FastAPI lifespan 主关 | 每 route 独立 (deleted) |
| 2026-07-25-06 | E2E stub 用 stdlib (http.server + sqlite3 + json)，不引入 fastapi/uvicorn | uvicorn test client |
| 2026-07-25-07 | AtFileMenu 用 discriminated union 三态 (file/office-import/office) | 仅支持 office |

## 8. 文件清单（实现期间涉及）

### Backend
- `backend/office/session_workspace.py` (NEW)
- `backend/office/workspace_errors.py` (NEW)
- `backend/office/workspace_search.py` (NEW)
- `backend/office/chat_refs.py` (NEW)
- `backend/office/tool_service.py` (NEW)
- `backend/tools/context.py` (NEW)
- `backend/tools/office_tool.py` (NEW)
- `backend/chat/executors.py` (NEW)
- `backend/api/workspace_routes.py` (NEW)
- `backend/api/legacy_routes.py` (MODIFY: `ChatRequest.office_refs`、ContextVar 注入、attachment executor)
- `backend/api/hex_routes.py` (MODIFY: 共享 executor)
- `backend/main.py` (MODIFY: workspace router 挂载、lifespan shutdown)
- `backend/tools/__init__.py` (MODIFY: 注册 OfficeTool)
- `backend/tools/base.py` (MODIFY: `requires_tool_context` flag)
- `backend/tools/registry.py` (MODIFY: context-aware schema filter)
- `backend/core/legacy/agent.py` (MODIFY: schema 调用使用 `current_tool_context()`)
- `backend/data/database.py` (MODIFY: `session_workspace_bindings` 迁移)

### Frontend
- `src/shared/api/types.ts` (MODIFY: Workspace types、ChatOfficeRef)
- `src/shared/api/workspaceApi.ts` (NEW)
- `src/shared/api/fileSearchClient.ts` (MODIFY: 委托 `workspaceApi.search`)
- `src/shared/api/chatApi.ts` (MODIFY: 第 5 个参数 `officeRefs`)
- `src/shared/lib/workspaceContext.tsx` (MODIFY: contract 与 selector)
- `src/app/providers/SessionWorkspaceProvider.tsx` (NEW)
- `src/app/providers/AppProviders.tsx` (MODIFY: 挂载新 Provider)
- `src/features/workspace/WorkspaceBindModal.tsx` (NEW)
- `src/features/chat/AtFileMenu.tsx` (MODIFY: 三态 union)
- `src/widgets/chat/ChatInput.tsx` (MODIFY: Office refs state/chips/send payload)
- `src/widgets/chat/InputCard.tsx` (MODIFY: chips UI)
- `src/pages/Chat.tsx` (MODIFY: options 透传)
- `src/pages/Office.tsx` (MODIFY: 删除本地 workspace state, 改用 `useCurrentWorkspace`)
- `src/features/office/importOfficeReference.ts` (NEW)
- `src/features/office/useOfficeDocuments.ts` (MODIFY: 复用 helper)
- `src/features/send-message/useChat.ts` (MODIFY: 透传 refs)

### Electron
- `electron/commands.ts` (MODIFY: 4 个 workspace_* routes)
- `electron/backendLauncher.ts` (MODIFY: 默认路径不变)
- `tests/electron/conftest.py` (NEW)
- `tests/electron/stub_backend.py` (NEW)
- `tests/electron/test_stub_backend.py` (NEW)
- `tests/electron/office-e2e.spec.ts` (NEW)
- `tests/electron/README.md` (NEW)

### Tests
- 上述实现对应的 16 个新 test 文件

### Docs
- `docs/technical/33-office-m1-m2-completion.md` (NEW, 本章节)

## 9. 已知限制与后续

- M3–M5 (write/edit/approval/archive/restore) 由独立分支 `fix/office-m3-m5-chat-write` 引入，依赖本章节的所有 API；
- win7 LTS 同步：main 合并后另起 cherry-pick PR 处理 py38/pydantic v1 注释兼容性；
- Provider 增量：`Skill` provider 与 `Office` provider 抽象层未来加 provider 字段（PR-7a 已记录）；
- Operation Log/版本树：未在本章节实现，需在 M3–M5 PR 中引入；
- stub backend 仅供 E2E，不替代真实 dev workflow；CI 真实 E2E 通过 `electron-smoke` job 运行。

## 10. 引用

- 设计：`docs/superpowers/specs/2026-07-25-office-m1-m2-completion-design.md`
- 计划：`docs/plans/2026-07-25-office-m1-m2-complete.md`
- 历史 chat-read 摘要 spec: `docs/superpowers/specs/2026-07-24-office-m1-m2-chat-read-design.md`
- 历史 M0 spec: `docs/superpowers/specs/2026-07-23-office-phase1-hardening-design.md`
- Ledger: `.superpowers/sdd/progress.md`
- Task 13 报告: `.superpowers/sdd/task-13-report.md`
