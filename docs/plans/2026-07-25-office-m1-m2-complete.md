# Office M1–M2 Complete Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 session-scoped Workspace、Office 文件引用、`office_list`/`office_read`、统一 Workspace UI 状态、共享 attachment executor 与 Electron→Python stub E2E，使 M3–M5 获得安全且可验证的只读基础层。

**Architecture:** SQLite current-state binding row 以 generation 失效旧请求；legacy `/api/v1/chat/stream` 在创建 stream 前完成 binding/ref 授权，并用 request-scoped ContextVar 动态暴露 Office tools。Renderer 以 `SessionWorkspaceProvider` 为唯一 Workspace 真相源，Office 搜索/导入生成无本地路径的 `ChatOfficeRef`；Electron 测试使用严格隔离的 stdlib Python stub 验证跨进程契约。

**Tech Stack:** Python 3.11（共享模型保持 Python 3.8/Pydantic v1 可解析注解）、FastAPI、SQLite、React 18、TypeScript、Zustand、Electron 21、Vitest、pytest、Playwright。

## Global Constraints

- Backend 命令必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；禁止系统 Python、conda base 和 `--user` 安装。
- 当前实现分支固定为 `feat/office-m1-m2-complete`，基线为 `main@48eeb1c`；禁止直接在 `main` 提交。
- 不修改、合并或删除 `release/win7`；不修改 `backend/requirements-py38.txt`。Win7 只在 main 合并后另开 cherry-pick PR。
- Backend 公共模型使用 `typing.Optional/List/FrozenSet/Literal`；不使用 PEP 604 `X | Y` 或 PEP 585 `list[X]` 作为 Pydantic runtime annotation。
- 本计划不实现 M3–M5 的 create/edit/approval/archive/restore、operation log 或 hex Office adapter。
- 本计划不删除 stash、旧 worktree、本地残留分支或远端 feature branch。
- LLM/tool schema 只接收 `doc_id`；不得接收 `workspace_path`、`file_path` 或 renderer `source_path`。
- 所有路径校验复用 `backend/office/path_safety.py` 与 `backend/office/storage.py::validate_workspace`，禁止字符串前缀 containment。
- Office import 保持 copy-only；源文件永不移动或删除。副作用调用不自动重试。
- 每个任务严格 RED → GREEN → REFACTOR；每个任务结束前运行 targeted tests、review diff，并创建独立 Conventional Commit。
- Backend、Frontend、Electron 新增关键代码覆盖率不得低于 80%；任何 CRITICAL/HIGH review finding 阻止进入下一阶段。
- 权威设计：`docs/superpowers/specs/2026-07-25-office-m1-m2-completion-design.md`。

---

## File Map

### Backend domain and API

| File | Action | Responsibility |
|---|---|---|
| `backend/data/database.py` | Modify | 创建 `session_workspace_bindings` current-state table/index |
| `backend/office/workspace_errors.py` | Create | 安全、无路径泄露的 binding/search/domain exceptions |
| `backend/office/session_workspace.py` | Create | bind/get/revoke/generation repository |
| `backend/office/workspace_search.py` | Create | active Workspace 内受限文件搜索与 managed Office 合并 |
| `backend/office/storage.py` | Modify | 单 SQL `get_document_in_workspace` |
| `backend/api/workspace_routes.py` | Create | 四个 session Workspace HTTP endpoints |
| `backend/main.py` | Modify | workspace router + executor shutdown lifecycle |
| `backend/api/legacy_routes.py` | Modify | canonical `ChatRequest.office_refs`、pre-stream authorization、tool context |
| `backend/office/chat_refs.py` | Create | immutable pre-stream Office ref authorization |
| `backend/tools/context.py` | Create | request-scoped `ToolExecutionContext` ContextVar |
| `backend/tools/base.py` | Modify | `requires_tool_context` capability flag |
| `backend/tools/registry.py` | Modify | context-aware Office schema filtering |
| `backend/core/legacy/agent.py` | Modify | schema lookup 使用 current context |
| `backend/office/tool_service.py` | Create | generation/doc-scope validated list/read service |
| `backend/tools/office_tool.py` | Create | `OfficeListTool`/`OfficeReadTool` wrappers |
| `backend/tools/__init__.py` | Modify | 注册两个 Office tools |
| `backend/chat/executors.py` | Create | 唯一 lazy attachment executor manager |
| `backend/api/hex_routes.py` | Modify | 移除独立 executor，复用共享 resolver |

### Electron and renderer

| File | Action | Responsibility |
|---|---|---|
| `electron/commands.ts` | Modify | 四个 Workspace command routes |
| `electron/backendLauncher.ts` | Modify | 非 packaged E2E stub launch plan |
| `src/shared/api/types.ts` | Modify | binding/search/`ChatOfficeRef` shared types |
| `src/shared/api/workspaceApi.ts` | Create | typed bind/get/revoke/search client |
| `src/shared/api/fileSearchClient.ts` | Modify | session-scoped search；不再直读 `officeApi.listDocuments` |
| `src/shared/lib/workspaceContext.tsx` | Modify | context contract 和 selectors |
| `src/app/providers/SessionWorkspaceProvider.tsx` | Create | session-aware binding state machine |
| `src/app/providers/AppProviders.tsx` | Modify | 挂载 `SessionWorkspaceProvider` |
| `src/features/workspace/WorkspaceBindModal.tsx` | Create | native folder picker + bind/revoke/retry UI |
| `src/features/workspace/index.ts` | Create | feature exports |
| `src/pages/Office.tsx` | Modify | 删除 local Workspace 真相源 |
| `src/features/office/importOfficeReference.ts` | Create | 复用 managed gateway 导入并返回 `ChatOfficeRef` |
| `src/features/office/useOfficeDocuments.ts` | Modify | 复用 import helper，保持 token cleanup |
| `src/features/chat/AtFileMenu.tsx` | Modify | 回传 discriminated selection，不伪造普通文件 ref |
| `src/widgets/chat/ChatInput.tsx` | Modify | 保存 Office refs/chips 并随消息提交 |
| `src/widgets/chat/InputCard.tsx` | Modify | Office ref chip/remove UI |
| `src/pages/Chat.tsx` | Modify | options 透传到 `useChat.sendMessage`；绑定入口 |
| `src/features/send-message/useChat.ts` | Modify | 将 refs 传给 `chatApi.chatStream` |
| `src/shared/api/chatApi.ts` | Modify | 第五个可选 `officeRefs` 参数 |

### Tests and docs

| File | Action | Responsibility |
|---|---|---|
| `tests/packaging/package-version-contract.spec.ts` | Create | package/lock root version parity |
| `backend/tests/unit/office/test_session_workspace.py` | Create | repository/generation/security |
| `backend/tests/unit/office/test_workspace_search.py` | Create | search scope/dedupe/limits |
| `backend/tests/integration/test_workspace_routes.py` | Create | HTTP/IPC contract backend side |
| `electron/__tests__/workspaceCommands.test.ts` | Create | command route encoding |
| `src/shared/api/__tests__/workspaceApi.test.ts` | Create | typed client contract |
| `src/app/providers/__tests__/SessionWorkspaceProvider.test.tsx` | Create | state machine/race/error tests |
| `src/features/workspace/__tests__/WorkspaceBindModal.test.tsx` | Create | binding UI |
| `backend/tests/unit/office/test_chat_refs.py` | Create | pre-stream authorization unit tests |
| `backend/tests/integration/test_chat_stream_office_refs.py` | Create | pre-stream authorization route tests |
| `src/features/chat/__tests__/AtFileMenu.ref-selection.test.tsx` | Create | file/managed/unmanaged union |
| `src/widgets/chat/__tests__/ChatInput.officeRefs.test.tsx` | Create | ref state/chips/send payload |
| `backend/tests/unit/tools/test_context.py` | Create | ContextVar isolation |
| `backend/tests/unit/tools/test_registry_office_filter.py` | Create | dynamic schema filtering |
| `backend/tests/unit/office/test_tool_service.py` | Create | read/list authorization/output limits |
| `backend/tests/unit/tools/test_office_tool.py` | Create | wrappers fail-closed |
| `backend/tests/integration/test_chat_office_tools.py` | Create | legacy tool loop integration |
| `backend/tests/unit/chat/test_executors.py` | Create | shared executor lifecycle |
| `electron/__tests__/backendLauncher.stub.test.ts` | Create | launch override isolation |
| `tests/fixtures/office/sample.docx` | Create | synthetic copy-only E2E fixture；stub 不解析 OOXML |
| `tests/fixtures/office_chat_backend_stub.py` | Create | stdlib HTTP/NDJSON backend stub |
| `backend/tests/unit/test_office_chat_backend_stub.py` | Create | stub contract tests |
| `tests/electron/m1-m2-stub.e2e.ts` | Create | Electron→Python full flow |
| `playwright.config.ts` | Modify | 为 stub E2E 固定 60 秒 timeout、失败 trace 和 screenshot |
| `.github/workflows/ci.yml` | Modify | setup Python + explicit stub E2E step |
| `docs/technical/33-office-m1-m2-workspace-binding.md` | Create | implementation architecture/security |
| `docs/user-manual/07-office-workspace.md` | Create | bind/import/reference/read usage |
| `docs/technical/README.md` | Modify | chapter 33 index |
| `docs/user-manual/README.md` | Modify | chapter 07 index |
| `docs/superpowers/specs/2026-07-23-office-chat-native-crud-design.md` | Modify | M1–M2 implementation status |
| `docs/superpowers/plans/2026-07-23-office-m1-m2-chat-read.md` | Delete at completion | remove superseded broad plan |
| `docs/superpowers/plans/2026-07-24-office-m1-m2-chat-read.md` | Delete at completion | remove completed narrow plan |
| `docs/plans/2026-07-25-office-m1-m2-complete.md` | Delete at completion | active plan lifecycle |

---

### Task 1: Enforce package metadata version parity

**Files:**
- Create: `tests/packaging/package-version-contract.spec.ts`
- Modify: `package-lock.json:3,9`

**Interfaces:**
- Consumes: `package.json.version`, `package-lock.json.version`, `package-lock.json.packages[""] .version`.
- Produces: permanent packaging contract requiring all three values to equal `0.4.5-alpha.28`.

- [ ] **Step 1: Write the failing contract test**

```ts
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

interface PackageLockRoot {
  version: string;
  packages: Record<string, { version?: string }>;
}

describe('package metadata version contract', () => {
  it('keeps package.json and both package-lock root versions equal', () => {
    const root = process.cwd();
    const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')) as {
      version: string;
    };
    const lock = JSON.parse(
      readFileSync(resolve(root, 'package-lock.json'), 'utf8'),
    ) as PackageLockRoot;

    expect(lock.version).toBe(pkg.version);
    expect(lock.packages['']?.version).toBe(pkg.version);
  });
});
```

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- tests/packaging/package-version-contract.spec.ts
```

Expected: FAIL showing `0.4.4-alpha.1` does not equal `0.4.5-alpha.28`.

- [ ] **Step 3: Apply the minimal lockfile correction**

Change only both root version fields to `0.4.5-alpha.28`. Do not apply or drop `stash@{0}`; reproduce only its two-line correction in the feature branch.

- [ ] **Step 4: Run GREEN and inspect the diff**

```bash
npm run test:run -- tests/packaging/package-version-contract.spec.ts
git diff -- package-lock.json tests/packaging/package-version-contract.spec.ts
```

Expected: 1 passing test; lockfile diff contains exactly two version replacements.

- [ ] **Step 5: Commit**

```bash
git add package-lock.json tests/packaging/package-version-contract.spec.ts
git commit -m "test(packaging): enforce package version parity"
```

---

### Task 2: Add session Workspace binding repository

**Files:**
- Create: `backend/office/workspace_errors.py`
- Create: `backend/office/session_workspace.py`
- Modify: `backend/data/database.py:157-197`
- Modify: `backend/office/storage.py:199-223`
- Test: `backend/tests/unit/office/test_session_workspace.py`

**Interfaces:**
- Consumes: `backend.office.storage.validate_workspace`, SQLite `sessions`, `office_documents`.
- Produces:

```text
SessionWorkspaceBinding(session_id, workspace_path, generation, activated_at, revoked_at)
bind_session_workspace(conn, session_id, workspace_path, now_ms=None) -> SessionWorkspaceBinding
get_workspace_binding(conn, session_id) -> Optional[SessionWorkspaceBinding]
get_active_workspace(conn, session_id, expected_generation=None) -> Optional[SessionWorkspaceBinding]
revoke_session_workspace(conn, session_id, now_ms=None) -> SessionWorkspaceBinding
get_document_in_workspace(conn, document_id, workspace_path) -> Optional[OfficeDocumentSummary]
```

- [ ] **Step 1: Write repository RED tests**

```python
def test_rebind_increments_generation_and_replaces_current_path(conn, work_a, work_b):
    first = bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    second = bind_session_workspace(conn, "session-a", str(work_b), now_ms=2000)

    assert first.generation == 1
    assert second.generation == 2
    assert second.workspace_path == str(work_b.resolve())
    assert second.revoked_at is None


def test_revoke_is_idempotent_and_invalidates_old_generation(conn, work_a):
    binding = bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    revoked = revoke_session_workspace(conn, "session-a", now_ms=2000)
    repeated = revoke_session_workspace(conn, "session-a", now_ms=3000)

    assert revoked.generation == binding.generation + 1
    assert repeated == revoked
    assert get_active_workspace(conn, "session-a", binding.generation) is None
```

Also add exact tests for unknown session, canonical symlink path, unbound get, revoked get, generation mismatch, cross-session isolation, and document scoping by `id + workspace_path + archived_at IS NULL`.

- [ ] **Step 2: Run RED**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_session_workspace.py -x -q
```

Expected: collection fails because `backend.office.session_workspace` does not exist.

- [ ] **Step 3: Add safe domain errors**

```python
class WorkspaceBindingError(Exception):
    code = "workspace_binding_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_message = message


class WorkspaceSessionNotFoundError(WorkspaceBindingError):
    code = "session_not_found"


class WorkspaceNotBoundError(WorkspaceBindingError):
    code = "workspace_not_bound"


class WorkspaceRevokedError(WorkspaceBindingError):
    code = "workspace_revoked"


class WorkspaceGenerationMismatchError(WorkspaceBindingError):
    code = "workspace_generation_mismatch"


class WorkspacePathMismatchError(WorkspaceBindingError):
    code = "workspace_path_mismatch"


class WorkspaceDocumentNotFoundError(WorkspaceBindingError):
    code = "document_not_found"
```

Messages must not interpolate absolute paths.

- [ ] **Step 4: Add the idempotent table migration**

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_workspace_bindings (
        session_id TEXT PRIMARY KEY,
        workspace_path TEXT NOT NULL,
        generation INTEGER NOT NULL DEFAULT 1,
        activated_at INTEGER NOT NULL,
        revoked_at INTEGER NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
""")
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_session_workspace_active "
    "ON session_workspace_bindings(session_id, revoked_at)"
)
conn.commit()
```

- [ ] **Step 5: Implement frozen mapping and atomic bind/revoke**

Use `@dataclass(frozen=True)` with `typing.Optional`. Rebind uses the parameterized SQLite upsert specified in the approved design, clears revoke, and increments generation. Validate session existence before insert and canonicalize with `validate_workspace(Path(workspace_path))`.

- [ ] **Step 6: Implement scoped document lookup**

```python
def get_document_in_workspace(
    conn: sqlite3.Connection,
    document_id: str,
    workspace_path: str,
) -> Optional[OfficeDocumentSummary]:
    row = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at
        FROM office_documents
        WHERE id = ? AND workspace_path = ? AND archived_at IS NULL
        """,
        (document_id, workspace_path),
    ).fetchone()
    return None if row is None else _row_to_summary(row)
```

- [ ] **Step 7: Run GREEN**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_session_workspace.py \
  backend/tests/unit/office/test_storage.py -q
```

Expected: all pass and error responses contain no submitted absolute paths.

- [ ] **Step 8: Commit**

```bash
git add backend/data/database.py backend/office/workspace_errors.py \
  backend/office/session_workspace.py backend/office/storage.py \
  backend/tests/unit/office/test_session_workspace.py
git commit -m "feat(office): bind workspaces to chat sessions"
```

---

### Task 3: Add bounded Workspace search and HTTP routes

**Files:**
- Create: `backend/office/workspace_search.py`
- Create: `backend/api/workspace_routes.py`
- Modify: `backend/main.py:20-31,339-357`
- Test: `backend/tests/unit/office/test_workspace_search.py`
- Test: `backend/tests/integration/test_workspace_routes.py`

**Interfaces:**
- Consumes Task 2 repository.
- Produces:

```text
WorkspaceSearchResult(name, kind, doc_type, doc_id, size_bytes, needs_import, source_path)
search_workspace_files(conn, session_id, query, limit=20) -> List[WorkspaceSearchResult]
PUT    /api/v1/sessions/{session_id}/workspace
GET    /api/v1/sessions/{session_id}/workspace
DELETE /api/v1/sessions/{session_id}/workspace
GET    /api/v1/sessions/{session_id}/workspace/files?q={query}&limit={limit}
```

- [ ] **Step 1: Write search RED tests**

Cover empty query, case-insensitive matching, managed Office result first, unmanaged Office `needs_import=True`, normal file, managed-path dedupe, symlink escape skip, 201-character query rejection, limits 0/51 rejection, and combined cap.

```python
def test_search_deduplicates_managed_office_file(conn, binding, managed_doc):
    results = search_workspace_files(conn, binding.session_id, "report", limit=20)

    assert len(results) == 1
    assert results[0].doc_id == managed_doc.id
    assert results[0].needs_import is False
    assert results[0].source_path is None
```

- [ ] **Step 2: Run search RED**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_workspace_search.py -x -q
```

Expected: import failure.

- [ ] **Step 3: Implement deterministic bounded search**

List managed docs first, build resolved managed paths, then scan sorted `Path.rglob("*")` candidates until `limit`. Every candidate goes through `resolve_within`; skip per-file `OSError` and containment failures. Only renderer import results may include `source_path`.

- [ ] **Step 4: Write route RED tests**

```python
async def test_get_unbound_workspace_returns_null(client, session_id):
    response = await client.get(f"/api/v1/sessions/{session_id}/workspace")
    assert response.status_code == 200
    assert response.json() == {"binding": None}


async def test_search_without_binding_is_forbidden(client, session_id):
    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/files",
        params={"q": "report", "limit": 20},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"
```

Also cover bind/get/rebind/revoke, unknown session 404, invalid path 400 without path leak, Pydantic 422, and response shape.

- [ ] **Step 5: Run route RED**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/integration/test_workspace_routes.py -x -q
```

Expected: 404 because router is not mounted.

- [ ] **Step 6: Implement typed routes and safe exception mapping**

Success responses match the approved spec. A representative non-2xx body is `{"detail":{"code":"workspace_not_bound","message":"当前会话尚未绑定工作区"}}`; never reuse the Office handler that exposes `file_path`.

- [ ] **Step 7: Mount the router once and run GREEN**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_workspace_search.py \
  backend/tests/integration/test_workspace_routes.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/office/workspace_search.py backend/api/workspace_routes.py \
  backend/main.py backend/tests/unit/office/test_workspace_search.py \
  backend/tests/integration/test_workspace_routes.py
git commit -m "feat(api): expose session workspace routes"
```

---

### Task 4: Add Electron routes and typed renderer client

**Files:**
- Modify: `electron/commands.ts:27-45`
- Create: `electron/__tests__/workspaceCommands.test.ts`
- Modify: `src/shared/api/types.ts:6-46`
- Create: `src/shared/api/workspaceApi.ts`
- Create: `src/shared/api/__tests__/workspaceApi.test.ts`
- Modify: `src/shared/api/index.ts`

**Interfaces:**

```text
workspaceApi.bind(sessionId, workspacePath) -> Promise<{ binding: SessionWorkspaceBinding }>
workspaceApi.get(sessionId) -> Promise<{ binding: SessionWorkspaceBinding | null }>
workspaceApi.revoke(sessionId) -> Promise<{ revoked: boolean; generation: number }>
workspaceApi.search(sessionId, query, limit=20) -> Promise<WorkspaceSearchResponse>
```

- [ ] **Step 1: Write Electron RED tests**

```ts
it('encodes session, query, and bounded limit', () => {
  const route = COMMAND_ROUTES.workspace_search_files;
  expect(route?.method).toBe('GET');
  expect(route?.path({ sessionId: 's/a', query: 'Q&A', limit: 20 })).toBe(
    '/api/v1/sessions/s%2Fa/workspace/files?q=Q%26A&limit=20',
  );
});
```

Assert all four routes, methods, `/api/v1`, encoding, and default/clamped limits.

- [ ] **Step 2: Run Electron RED**

```bash
npm run test:run -- electron/__tests__/workspaceCommands.test.ts
```

Expected: routes undefined.

- [ ] **Step 3: Implement exact command routes**

Add `workspace_bind`, `workspace_get`, `workspace_revoke`, `workspace_search_files` using encoded session/query and limit 1–50.

- [ ] **Step 4: Write workspaceApi RED tests**

```ts
await workspaceApi.bind('session-a', '/synthetic/work');
expect(mockInvoke).toHaveBeenCalledWith('workspace_bind', {
  sessionId: 'session-a',
  workspacePath: '/synthetic/work',
});
```

Cover all four methods and focused snake→camel response mapping.

- [ ] **Step 5: Implement shared types and client**

```ts
export interface SessionWorkspaceBinding {
  sessionId: string;
  workspacePath: string;
  generation: number;
  activatedAt: number;
  revokedAt: number | null;
}

export interface ChatOfficeRef {
  docId: string;
  docType: OfficeDocType;
  filename: string;
}
```

Do not expose backend snake_case to context/UI.

- [ ] **Step 6: Run GREEN and commit**

```bash
npm run test:run -- electron/__tests__/workspaceCommands.test.ts \
  src/shared/api/__tests__/workspaceApi.test.ts
npm run typecheck:electron
git add electron/commands.ts electron/__tests__/workspaceCommands.test.ts \
  src/shared/api/types.ts src/shared/api/workspaceApi.ts \
  src/shared/api/__tests__/workspaceApi.test.ts src/shared/api/index.ts
git commit -m "feat(frontend): add session workspace client"
```

---

### Task 5: Make session Workspace the only renderer state source

**Files:**
- Modify: `src/shared/lib/workspaceContext.tsx`
- Create: `src/app/providers/SessionWorkspaceProvider.tsx`
- Modify: `src/app/providers/AppProviders.tsx:29-43`
- Create: `src/features/workspace/WorkspaceBindModal.tsx`
- Create: `src/features/workspace/index.ts`
- Modify: `src/pages/Office.tsx:42-83`
- Test: `src/app/providers/__tests__/SessionWorkspaceProvider.test.tsx`
- Test: `src/features/workspace/__tests__/WorkspaceBindModal.test.tsx`
- Test: `src/pages/__tests__/Office.workspace.test.tsx`

**Interfaces:**

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

Exports: `SessionWorkspaceProvider`, `useWorkspaceContext`, `useCurrentWorkspace`.

- [ ] **Step 1: Write Provider RED tests**

Use deferred promises to prove stale-response suppression. Cover idle, loading, binding, null binding, error+refresh, bind, revoke, session change, and `useCurrentWorkspace`.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/app/providers/__tests__/SessionWorkspaceProvider.test.tsx
```

Expected: missing provider.

- [ ] **Step 3: Replace the context contract and implement Provider**

Use `createContext<WorkspaceContextValue | null>(null)`. Provider subscribes to `useStore(state => state.currentSessionId)` and uses a monotonically increasing request ID because desktop IPC does not support true abort. All state updates create new objects.

- [ ] **Step 4: Write and implement modal RED/GREEN**

Tests assert native `selectDirectory`, cancel, bind, busy, safe error/retry, and revoke. Use test IDs `workspace-bind-button`, `workspace-revoke-button`, `workspace-bind-error`.

- [ ] **Step 5: Migrate AppProviders and Office**

Mount `SessionWorkspaceProvider`; remove `Office.tsx` local `workspacePath` state/setter; use `useCurrentWorkspace() ?? null`; preserve stale-read guards and use the modal for bind/change.

- [ ] **Step 6: Run GREEN and commit**

```bash
npm run test:run -- \
  src/app/providers/__tests__/SessionWorkspaceProvider.test.tsx \
  src/features/workspace/__tests__/WorkspaceBindModal.test.tsx \
  src/pages/__tests__/Office.workspace.test.tsx \
  src/features/office/__tests__/useOfficeDocuments.test.ts
npm run typecheck
git add src/shared/lib/workspaceContext.tsx src/app/providers \
  src/features/workspace src/pages/Office.tsx src/pages/__tests__/Office.workspace.test.tsx
git commit -m "feat(frontend): unify session workspace state"
```

---

### Task 6: Authorize ChatOfficeRef before creating a legacy stream

**Files:**
- Modify: `backend/api/legacy_routes.py:102-125,974-1003`
- Create: `backend/office/chat_refs.py`
- Test: `backend/tests/unit/office/test_chat_refs.py`
- Test: `backend/tests/integration/test_chat_stream_office_refs.py`

**Interfaces:**

```text
ChatOfficeRef(doc_id, doc_type, filename)
AuthorizedOfficeRequest(session_id, binding_generation, office_doc_scope, workspace_path)
authorize_chat_office_request(conn, session_id, request_workspace_path, office_refs)
  -> Optional[AuthorizedOfficeRequest]
```

- [ ] **Step 1: Write authorization RED tests**

Cover no-binding/no-refs, no-binding/refs, active binding scope, raw path mismatch, foreign/unknown/archived refs, type/filename mismatch, and generation capture.

```python
def test_authorize_rejects_doc_from_other_workspace(conn, binding_a, doc_b):
    refs = [ChatOfficeRef(doc_id=doc_b.id, doc_type="word", filename="b.docx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)
```

- [ ] **Step 2: Run RED**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_chat_refs.py -x -q
```

Expected: module not found.

- [ ] **Step 3: Implement immutable authorization**

Return `AuthorizedOfficeRequest(session_id, binding_generation, office_doc_scope, workspace_path)`. `workspace_path` is backend-derived only. Validate refs against all visible docs in the active canonical Workspace.

- [ ] **Step 4: Add strict legacy DTOs**

Add `ChatOfficeRef` in `backend/office/chat_refs.py` as a strict Pydantic model using `typing.Literal`, bounded strings, and `extra="forbid"`; import it into `legacy_routes.py` and add `office_refs: List[ChatOfficeRef] = Field(default_factory=list)` to the existing legacy `ChatRequest`. Keep every existing LLM config field unchanged. Keeping the DTO beside its authorization function avoids a route↔domain circular import.

- [ ] **Step 5: Validate before StreamRegistry.create**

Call authorization synchronously in `chat_stream_create` before creating a stream ID/producer. Map `workspace_path_mismatch` to 400, unbound/revoked/generation authorization failures to 403, and scoped document misses to 404. No failed request may leave a registry entry.

- [ ] **Step 6: Run integration GREEN and commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_chat_refs.py \
  backend/tests/integration/test_chat_stream_office_refs.py -q
git add backend/office/chat_refs.py backend/api/legacy_routes.py \
  backend/tests/unit/office/test_chat_refs.py \
  backend/tests/integration/test_chat_stream_office_refs.py
git commit -m "feat(chat): authorize Office refs before streaming"
```

---

### Task 7: Carry managed Office refs through renderer Chat

**Files:**
- Modify: `src/shared/api/fileSearchClient.ts`
- Create: `src/features/office/importOfficeReference.ts`
- Modify: `src/features/office/useOfficeDocuments.ts`
- Modify: `src/features/chat/AtFileMenu.tsx`
- Modify: `src/widgets/chat/ChatInput.tsx`
- Modify: `src/widgets/chat/InputCard.tsx`
- Modify: `src/pages/Chat.tsx`
- Modify: `src/features/send-message/useChat.ts`
- Modify: `src/shared/api/chatApi.ts`
- Test: `src/features/chat/__tests__/AtFileMenu.ref-selection.test.tsx`
- Test: `src/widgets/chat/__tests__/ChatInput.officeRefs.test.tsx`
- Test: `src/shared/api/__tests__/fileSearchClient.test.ts`
- Test: `src/shared/api/__tests__/chatApi.office.test.ts`

**Interface:**

```ts
export type AtFileSelection =
  | { kind: 'file'; path: string; name: string }
  | { kind: 'office-import'; result: WorkspaceSearchResult }
  | { kind: 'office'; ref: ChatOfficeRef };
```

- [ ] **Step 1: Write search/menu RED tests**

`fileSearchClient.search(sessionId, query, options)` delegates to `workspaceApi.search`. `AtFileMenu` reads `sessionId` and `workspacePath` from `useWorkspaceContext` instead of receiving a raw workspace prop. Test normal file, managed Office, unmanaged Office mapped to `{ kind: 'office-import', result }`, timeout/abort, and missing session. AtFileMenu must never fabricate an Office ref for a normal file.

- [ ] **Step 2: Extract existing managed import lifecycle**

Implement `importOfficeReference(workspacePath, result)` with `importDroppedOfficeFile → officeApi.read* → completeOfficeImport`, and `discardOfficeImport` on error. Refactor `useOfficeDocuments` to reuse the helper without changing behavior.

- [ ] **Step 3: Add immutable ChatInput ref state/chips**

Dedupe by `docId`; managed selection inserts `@filename`; normal file inserts existing `@path`; `{ kind: 'office-import' }` awaits `importOfficeReference` then adds the returned ref. Add removable `office-ref-chip` UI and include `officeRefs` in `onSend` options. When context has no binding, Chat renders the existing `WorkspaceBindModal` entry point and keeps Office search disabled until bind succeeds.

- [ ] **Step 4: Propagate refs to chatApi**

Add optional refs to `Chat.handleSendMessage`, `useChat.sendMessage`, and the fifth `chatApi.chatStream` argument. Include `officeRefs` in `agent_chat_stream` invoke. Existing callers omitting refs remain unchanged.

- [ ] **Step 5: Run GREEN and commit**

```bash
npm run test:run -- \
  src/shared/api/__tests__/fileSearchClient.test.ts \
  src/shared/api/__tests__/chatApi.office.test.ts \
  src/features/chat/__tests__/AtFileMenu.ref-selection.test.tsx \
  src/widgets/chat/__tests__/ChatInput.officeRefs.test.tsx \
  src/features/office/__tests__/useOfficeDocuments.test.ts
npm run typecheck
git add src/shared/api/fileSearchClient.ts src/features/office \
  src/features/chat/AtFileMenu.tsx src/widgets/chat/ChatInput.tsx \
  src/widgets/chat/InputCard.tsx src/pages/Chat.tsx \
  src/features/send-message/useChat.ts src/shared/api/chatApi.ts \
  src/shared/api/__tests__ src/features/chat/__tests__/AtFileMenu.ref-selection.test.tsx \
  src/widgets/chat/__tests__/ChatInput.officeRefs.test.tsx
git commit -m "feat(chat): send managed Office references"
```

---

### Task 8: Add request-scoped tool context and schema filtering

**Files:**
- Create: `backend/tools/context.py`
- Modify: `backend/tools/base.py:70-86`
- Modify: `backend/tools/registry.py:89-105`
- Modify: `backend/core/legacy/agent.py:648-667`
- Test: `backend/tests/unit/tools/test_context.py`
- Test: `backend/tests/unit/tools/test_registry_office_filter.py`

- [ ] **Step 1: Write ContextVar and registry RED tests**

Cover default/set/reset/nesting/exceptions/concurrent tasks. Registry with no context returns normal schemas only; active context returns normal + Office; execution lookup remains available for wrapper fail-closed checks.

- [ ] **Step 2: Run RED**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/tools/test_context.py \
  backend/tests/unit/tools/test_registry_office_filter.py -x -q
```

Expected: missing module/signature.

- [ ] **Step 3: Implement context and correct filter semantics**

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    stream_id: str
    binding_generation: int
    office_doc_scope: FrozenSet[str]
```

Add `BaseTool.requires_tool_context = False`. Registry skips a tool only when `tool.requires_tool_context and context is None`; it never hides normal tools from an active context.

- [ ] **Step 4: Make SageAgent read current context**

Pass `current_tool_context()` into `get_schemas_for_llm`; preserve existing OpenAI schema shape/order.

- [ ] **Step 5: Run GREEN and commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/tools/test_context.py \
  backend/tests/unit/tools/test_registry_office_filter.py \
  backend/tests/unit/test_agent_run_loop.py -q
git add backend/tools/context.py backend/tools/base.py backend/tools/registry.py \
  backend/core/legacy/agent.py backend/tests/unit/tools
git commit -m "feat(tools): add request-scoped tool context"
```

---

### Task 9: Implement Office list/read tools and legacy integration

**Files:**
- Create: `backend/office/tool_service.py`
- Create: `backend/tools/office_tool.py`
- Modify: `backend/tools/__init__.py:19-46`
- Modify: `backend/api/legacy_routes.py:1001-1173`
- Test: `backend/tests/unit/office/test_tool_service.py`
- Test: `backend/tests/unit/tools/test_office_tool.py`
- Test: `backend/tests/integration/test_chat_office_tools.py`

**Interfaces:**

```text
OfficeToolService.list(session_id, binding_generation, query=None, doc_type=None, limit=50)
  -> List[dict]
OfficeToolService.read(session_id, binding_generation, doc_id, section="summary")
  -> dict
OfficeListTool.execute(query=None, doc_type=None, limit=50) -> ToolResult
OfficeReadTool.execute(doc_id, section="summary") -> ToolResult
```

- [ ] **Step 1: Write service RED tests**

Cover generation/revoke/rebind, workspace/archived filtering, policy limits, indistinguishable not-found, summary/head/all deterministic truncation, and no absolute path in results.

- [ ] **Step 2: Implement service authorization and bounded output**

Every method rechecks `get_active_workspace(conn, session_id, expected_generation=binding_generation)`; `read` uses scoped lookup and existing readers. Apply `ToolPolicy.max_read_bytes`, `max_output_bytes`, and `max_result_items`. If `all` exceeds output limit, return bounded `head` with `truncated=True`.

- [ ] **Step 3: Write/implement wrapper RED/GREEN**

Both wrappers set `requires_tool_context=True`, expose schemas containing no path parameter, return `missing_tool_context` without context, and map authorization failures to safe error codes. Register them in `register_all_tools`.

- [ ] **Step 4: Write legacy tool-loop integration test**

Mock LLM responses `office_list → office_read → final`; assert acting/observing/done, tool result in next LLM call, no binding hides Office schemas, and rebind between calls fails closed.

- [ ] **Step 5: Set/reset context around producer loop**

Build context from Task 6 authorization; set before `async for agent.run_loop`, reset in `finally`. With no binding, set no context; normal tools remain available.

- [ ] **Step 6: Run GREEN and commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/office/test_tool_service.py \
  backend/tests/unit/tools/test_office_tool.py \
  backend/tests/integration/test_chat_office_tools.py -q
git add backend/office/tool_service.py backend/tools/office_tool.py \
  backend/tools/__init__.py backend/api/legacy_routes.py \
  backend/tests/unit/office/test_tool_service.py \
  backend/tests/unit/tools/test_office_tool.py \
  backend/tests/integration/test_chat_office_tools.py
git commit -m "feat(office): expose scoped list and read tools"
```

---

### Task 10: Share one attachment executor lifecycle

**Files:**
- Create: `backend/chat/executors.py`
- Modify: `backend/api/legacy_routes.py:27-51,1047-1052`
- Modify: `backend/api/hex_routes.py:28-57,162-170`
- Modify: `backend/main.py:132-282`
- Test: `backend/tests/unit/chat/test_executors.py`

**Interfaces:**

```text
await resolve_attachments(text, workspace) -> str
shutdown_attachment_executor() -> None
_reset_attachment_executor_for_tests() -> None
```

- [ ] **Step 1: Write executor RED tests**

Assert lazy creation, max_workers=4/thread prefix, off-loop execution, shared instance, idempotent shutdown, and reset/recreate.

- [ ] **Step 2: Implement locked manager**

Export `resolve_attachments`, `shutdown_attachment_executor`, private test reset. Swap executor reference to `None` under lock before shutdown and register one `atexit` fallback.

- [ ] **Step 3: Migrate both routes and lifespan**

Legacy passes only active binding canonical path; hex retains its existing `req.workspace_path or ""` compatibility. Delete both route-local pools and registrations. Shutdown manager in FastAPI lifespan.

- [ ] **Step 4: Run GREEN and commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/chat/test_executors.py \
  backend/tests/unit/chat/test_attachment_resolver.py \
  backend/tests/integration/test_chat_attachment_injection_legacy.py \
  backend/tests/integration/test_chat_attachment_injection_hex.py -q
git add backend/chat/executors.py backend/api/legacy_routes.py \
  backend/api/hex_routes.py backend/main.py backend/tests/unit/chat/test_executors.py
git commit -m "refactor(chat): share attachment executor lifecycle"
```

---

### Task 11: Add isolated Python stub launcher and server

**Files:**
- Modify: `electron/backendLauncher.ts:57-79,95-135`
- Create: `electron/__tests__/backendLauncher.stub.test.ts`
- Create: `tests/fixtures/office_chat_backend_stub.py`
- Create: `tests/fixtures/office/sample.docx`
- Create: `backend/tests/unit/test_office_chat_backend_stub.py`

- [ ] **Step 1: Write launcher RED tests**

Assert explicit mode uses `SAGE_E2E_PYTHON`, `SAGE_E2E_STUB_PATH`, `SAGE_E2E_REQUEST_LOG`; missing any returns a configuration error; packaged mode ignores overrides; normal dev remains conda.

- [ ] **Step 2: Implement non-packaged branch**

Return reason `e2e-python-stub` and args `[stubPath, '--port', port, '--request-log', requestLog]`. Extend reason unions. Never enter this branch when `isPackaged=true`.

- [ ] **Step 3: Write stub contract RED tests**

Start subprocess on an ephemeral port. Cover health, settings, skills, sessions/messages, binding/search, Office read persistence, stream create/attach, revoke authorization, and JSONL logging.

- [ ] **Step 4: Implement stdlib stub**

Use `ThreadingHTTPServer`, process-local dictionaries protected by `threading.Lock`, and only the endpoints required by App/Chat/Office. `GET /api/v1/settings` returns a complete canonical `AppSettings`: endpoint id `stub`, base URL `http://127.0.0.1/stub`, model id `stub-model`, default proxy/wiki fields, and `version: "3.0.0"`; this enables ChatInput without external network access. Never parse the synthetic `.docx`; derive doc ID from managed parent and return the existing response shape.

- [ ] **Step 5: Run GREEN and commit**

```bash
npm run test:run -- electron/__tests__/backendLauncher.stub.test.ts
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_office_chat_backend_stub.py -q
git add electron/backendLauncher.ts electron/__tests__/backendLauncher.stub.test.ts \
  tests/fixtures/office_chat_backend_stub.py tests/fixtures/office/sample.docx \
  backend/tests/unit/test_office_chat_backend_stub.py
git commit -m "test(e2e): add isolated Python backend stub"
```

---

### Task 12: Drive Electron→Python flow and add CI coverage

**Files:**
- Create: `tests/electron/m1-m2-stub.e2e.ts`
- Modify: `playwright.config.ts`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write failing E2E**

Skip unless `SAGE_E2E_STUB=1`. Launch Electron with stub variables/temp user data. Monkeypatch `dialog.showOpenDialog` from `electronApp.evaluate` to return the temporary Workspace. Drive binding, synthetic drop, Office read/import, Chat `@sample`, Office chip, send/reply, JSONL assertion, revoke failure, and plain Chat success.

- [ ] **Step 2: Run RED**

```bash
SAGE_E2E_STUB=1 \
SAGE_E2E_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python \
SAGE_E2E_STUB_PATH="$PWD/tests/fixtures/office_chat_backend_stub.py" \
SAGE_E2E_REQUEST_LOG=/tmp/sage-m1-m2-stub-requests.jsonl \
npx playwright test tests/electron/m1-m2-stub.e2e.ts --project=electron --reporter=line
```

Expected: failure at the first incomplete cross-process contract, with trace retained.

- [ ] **Step 3: Complete stable locators/config and run GREEN twice**

Use `workspace-bind-button`, `office-file-picker-word`, `office-ref-chip`, and accessible send controls. Keep existing smoke semantics. Run twice after deleting only temp JSONL/user data; both runs must pass without port/process residue.

- [ ] **Step 4: Add explicit CI step**

In `electron-smoke`, setup Python 3.11, retain current smoke, add a separate stub E2E step, and upload trace/screenshots on failure.

- [ ] **Step 5: Verify and commit**

```bash
npm run typecheck:electron
npm run test:run -- electron/__tests__/backendLauncher.stub.test.ts \
  electron/__tests__/workspaceCommands.test.ts
npx playwright test tests/electron/m1-m2-stub.e2e.ts --project=electron --reporter=line
git add tests/electron/m1-m2-stub.e2e.ts playwright.config.ts .github/workflows/ci.yml
git commit -m "test(e2e): cover session-scoped Office chat"
```

---

### Task 13: Archive docs, run full gates, and review whole branch

**Files:**
- Create: `docs/technical/33-office-m1-m2-workspace-binding.md`
- Create: `docs/user-manual/07-office-workspace.md`
- Modify: `docs/technical/README.md`
- Modify: `docs/user-manual/README.md`
- Modify: `docs/superpowers/specs/2026-07-23-office-chat-native-crud-design.md`
- Delete: two superseded `docs/superpowers/plans/*office-m1-m2-chat-read.md`
- Delete after all checks: this active plan

- [ ] **Step 1: Write observed technical/user docs and update indexes**

Technical chapter records exact table/API/commands/context/tools/executor/stub/security/error codes. User chapter records bind/rebind/revoke/import/reference/list/read behavior and clearly states writes/archives are not available.

- [ ] **Step 2: Update broad spec status and remove superseded plans**

Keep the narrow 2026-07-24 spec as historical implemented design. Delete only the two superseded execution plans.

- [ ] **Step 3: Run backend gates**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests \
  --cov=backend --cov-report=term-missing --cov-fail-under=80
./scripts/lint.sh check
/home/fz/anaconda3/envs/sage-backend/bin/python -m mypy \
  backend/office backend/tools backend/chat backend/api
(cd backend && PYTHONPATH=.. /home/fz/anaconda3/envs/sage-backend/bin/python -m importlinter)
```

- [ ] **Step 4: Run frontend/Electron/build/E2E gates**

```bash
npm run lint
npm run typecheck
npm run typecheck:electron
npm run test:coverage
npm run build
npm run electron:build
SAGE_E2E_STUB=1 \
SAGE_E2E_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python \
SAGE_E2E_STUB_PATH="$PWD/tests/fixtures/office_chat_backend_stub.py" \
SAGE_E2E_REQUEST_LOG=/tmp/sage-m1-m2-stub-requests.jsonl \
npx playwright test tests/electron/m1-m2-stub.e2e.ts --project=electron --reporter=line
```

Expected: every command exits 0; configured coverage floor is met.

- [ ] **Step 5: Run mandatory parallel reviews**

Run these agents in parallel on `main...HEAD`: `code-reviewer`, `security-reviewer`, `python-reviewer`, `typescript-reviewer`, and `pr-test-analyzer`. Fix every CRITICAL/HIGH finding and rerun affected targeted/full gates.

- [ ] **Step 6: Verify scope**

```bash
git diff --name-only main...HEAD
git diff --check main...HEAD
git status --short --branch
git diff main...HEAD -- backend/requirements-py38.txt
git log --oneline main..HEAD
```

Expected: no Win7 requirements diff, no M3–M5 write/approval modules, no cleanup of preserved stash/worktrees/remote branches, and a clean tree.

- [ ] **Step 7: Delete completed plans and commit docs**

```bash
git rm docs/plans/2026-07-25-office-m1-m2-complete.md \
  docs/superpowers/plans/2026-07-23-office-m1-m2-chat-read.md \
  docs/superpowers/plans/2026-07-24-office-m1-m2-chat-read.md
git add docs/technical docs/user-manual \
  docs/superpowers/specs/2026-07-23-office-chat-native-crud-design.md
git commit -m "docs(office): archive complete M1-M2 foundation"
```

- [ ] **Step 8: Prepare PR without merging**

Fetch/rebase only with user approval if `origin/main` advanced. Push the feature branch, create a PR to `main`, monitor CI, and stop on any failure. Do not merge or create a Win7 PR without separate user instruction.

---

## Plan Self-Review Matrix

| Spec requirement | Implemented by |
|---|---|
| lockfile parity | Task 1 |
| binding + generation | Task 2 |
| scoped document authorization | Tasks 2, 6, 9 |
| bounded Workspace search | Task 3 |
| HTTP/Electron/client | Tasks 3, 4 |
| single renderer state source | Task 5 |
| ChatOfficeRef without local path | Tasks 6, 7 |
| ordinary file compatibility | Task 7 discriminated union |
| request ContextVar/schema filter | Task 8 |
| Office list/read tools | Task 9 |
| shared executor lifecycle | Task 10 |
| isolated stdlib stub | Task 11 |
| Electron E2E + CI | Task 12 |
| ≥80% coverage/reviews/docs lifecycle | Task 13 |
| no M3–M5/Win7/residual cleanup | Global Constraints + Task 13 scope check |
