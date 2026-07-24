# Office M1-M2 Chat Read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Office 文档接入当前真实 legacy Chat，实现 session Workspace、`@`/拖放文件引用，以及 `office_list`/`office_read` 只读工具闭环。

**Architecture:** M1 将用户选择的 Workspace 和 Office 文件转换为 session-scoped `ChatOfficeRef`，LLM 不接触文件路径。M2 创建 request-scoped `ToolExecutionContext`，让 legacy `SageAgent.run_loop` 动态暴露 Office tools，并通过共享 `OfficeToolService` 完成 doc_id 授权、list 和结构化 read。

**Tech Stack:** Python 3.11 (`sage-backend` conda env)、FastAPI、Pydantic 2、SQLite、ToolRegistry/BaseTool、legacy SageAgent ReAct、Electron IPC、React/TypeScript、Vitest、pytest、Playwright。

## Global Constraints

- M0 必须已完成并处于干净分支；所有托管文件使用 M0 的 `managed_document_path`。
- 后端命令使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。
- 只支持 `.pptx/.docx/.xlsx`；Office tool 不接受 `file_path` 或 `workspace_path`。
- 每个 Chat session 绑定一个 Workspace；工具 Workspace 从 `session_id` 后端查询。
- `ChatOfficeRef` 只包含 `docId`、`docType`、`filename`。
- 无 active Workspace 时不向 LLM 暴露 Office tools。
- Office 二进制不作为 base64 发送给 LLM；Electron 先复制为 managed document。
- 每个任务采用 RED → GREEN → 验证 → 独立 Conventional Commit。

## File Map

### Backend

- Create: `backend/office/session_workspace.py` — binding repository and canonical path validation。
- Create: `backend/api/workspace_routes.py` — bind/get/revoke/search endpoints。
- Modify: `backend/main.py:298-355` — mount workspace routes。
- Modify: `backend/data/database.py:158-181` — `session_workspace_bindings` and `office_operation_log` tables。
- Modify: `backend/office/storage.py` — session-scoped document lookup/list helpers。
- Modify: `backend/api/legacy_routes.py:89-112,960-1144` — `office_refs` request and context injection。
- Create: `backend/tools/context.py` — request-scoped ToolExecutionContext。
- Modify: `backend/tools/registry.py` — context-aware schema filtering and execution。
- Modify: `backend/core/legacy/agent.py:449-609,648-667` — pass context through actual ReAct path。
- Create: `backend/office/tool_service.py` — session/doc_id authorization and read-only operations。
- Create: `backend/tools/office_tool.py` — `OfficeListTool` and `OfficeReadTool` BaseTool wrappers。
- Modify: `backend/tools/__init__.py:20-47` — register Office read tools。
- Create: `backend/tests/unit/office/test_session_workspace.py`。
- Create: `backend/tests/unit/office/test_tool_service_read.py`。
- Create: `backend/tests/unit/tools/test_office_tools.py`。
- Create: `backend/tests/integration/test_workspace_routes.py`。
- Create: `backend/tests/integration/test_chat_office_read.py`。

### Electron / Frontend

- Modify: `electron/commands.ts:13-196` — workspace bind/search routes。
- Modify: `electron/preload.ts:102-135` — workspace bind bridge and M0 Office import bridge reuse。
- Modify: `src/shared/types/electron-api.d.ts` — workspace and ChatOfficeRef types。
- Create: `src/shared/api/workspaceApi.ts`。
- Modify: `src/shared/api/chatApi.ts:67-175` — `officeRefs` payload。
- Modify: `src/shared/api/types.ts` — `ChatOfficeRef`, workspace/search response types。
- Modify: `src/features/send-message/useChat.ts:92-413` — send options and tool context display。
- Modify: `src/widgets/chat/ChatInput.tsx:16-107,160-230` — Office refs and drag-drop import。
- Modify: `src/features/chat/AtFileMenu.tsx`、`src/features/chat/useAtFileQuery.ts` — search result selection。
- Create: `src/widgets/chat/WorkspaceBindModal.tsx`。
- Modify: `src/pages/Chat.tsx:89-104` — bind Workspace before Office attachment/send。
- Create: `src/shared/api/__tests__/workspaceApi.test.ts`。
- Create: `src/features/chat/__tests__/AtFileMenu.office.test.tsx`。
- Create: `src/widgets/chat/__tests__/WorkspaceBindModal.test.tsx`。
- Modify: existing ChatInput/useChat tests or create focused tests beside them。

### E2E / Docs

- Create: `tests/e2e/chat-office-read.spec.ts`。
- Modify: `docs/superpowers/plans/2026-07-23-office-m1-m2-chat-read.md` checkboxes during execution。

---

### Task 1: 建立 session Workspace binding 和 operation summary 表

**Files:**
- Create: `backend/office/session_workspace.py`。
- Modify: `backend/data/database.py:158-181`。
- Modify: `backend/office/storage.py`。
- Create: `backend/tests/unit/office/test_session_workspace.py`。

**Interfaces:**

```python
@dataclass(frozen=True)
class SessionWorkspaceBinding:
    session_id: str
    workspace_path: Path
    activated_at: int
    revoked_at: int | None

def bind_session_workspace(
    conn: sqlite3.Connection,
    session_id: str,
    workspace_path: str,
    now_ms: int,
) -> SessionWorkspaceBinding:
    raise NotImplementedError

def get_active_workspace(
    conn: sqlite3.Connection,
    session_id: str,
) -> Path | None:
    raise NotImplementedError

def revoke_session_workspace(
    conn: sqlite3.Connection,
    session_id: str,
    now_ms: int,
) -> bool:
    raise NotImplementedError

def get_document_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    doc_id: str,
    include_archived: bool = False,
) -> OfficeDocumentSummary | None:
    raise NotImplementedError
```

Add tables:

```sql
CREATE TABLE IF NOT EXISTS session_workspace_bindings (
  session_id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  activated_at INTEGER NOT NULL,
  revoked_at INTEGER,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS office_operation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  proposal_id TEXT,
  tool_name TEXT NOT NULL,
  doc_id TEXT,
  outcome TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
```

- [ ] **Step 1: Write failing binding and isolation tests**

Test canonicalization, one active binding per session, revoke behavior, two sessions sharing one Workspace, and session A failing to retrieve a document whose `workspace_path` differs.

Example:

```python
def test_get_document_for_session_rejects_other_workspace(db, summaries):
    bind_session_workspace(db, 'session-a', '/tmp/work-a', 1000)
    assert get_document_for_session(db, 'session-a', summaries['work-b'].id) is None
```

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_session_workspace.py -q
```

Expected: FAIL because the repository and tables do not exist.

- [ ] **Step 3: Implement idempotent schema and repository**

Add `CREATE TABLE IF NOT EXISTS` to `Database.init_db`, canonicalize Workspace through M0 `validate_workspace`, upsert a session binding only after the directory validates, and implement the session/workspace join for document lookup.

- [ ] **Step 4: Run tests to verify GREEN**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_session_workspace.py tests/unit/office/test_storage.py -q
```

Expected: PASS, including revoked and cross-workspace cases.

- [ ] **Step 5: Commit the binding foundation**

```bash
cd /home/fz/project/sage && \
  git add backend/data/database.py backend/office/session_workspace.py \
  backend/office/storage.py backend/tests/unit/office/test_session_workspace.py && \
  git commit -m "feat: bind Office documents to chat workspaces"
```

### Task 2: 暴露 Workspace binding API 和 Electron client

**Files:**
- Create: `backend/api/workspace_routes.py`。
- Modify: `backend/main.py:298-355`。
- Modify: `electron/commands.ts:13-196`。
- Modify: `src/shared/api/types.ts`。
- Create: `src/shared/api/workspaceApi.ts`。
- Modify: `electron/preload.ts:102-135`。
- Modify: `src/shared/types/electron-api.d.ts`。
- Create: `backend/tests/integration/test_workspace_routes.py`。
- Create: `src/shared/api/__tests__/workspaceApi.test.ts`。

**Interfaces:**

```text
POST /api/v1/sessions/{session_id}/workspace
body: { workspace_path: string }
response: { session_id, workspace_path, activated_at }

GET /api/v1/sessions/{session_id}/workspace
response: binding | null

DELETE /api/v1/sessions/{session_id}/workspace
response: { session_id, revoked: true }

GET /api/v1/workspace/files/search?session_id=<session-id>&query=<url-encoded-query>
response: { files: WorkspaceSearchResult[], total: number }
```

```typescript
interface WorkspaceSearchResponse {
  files: WorkspaceSearchResult[];
  total: number;
}

interface SessionWorkspaceBinding {
  sessionId: string;
  workspacePath: string;
  activatedAt: number;
  revokedAt: number | null;
}

interface WorkspaceSearchResult {
  name: string;
  docType: 'ppt' | 'word' | 'excel' | null;
  docId: string | null;
  sizeBytes: number;
  needsImport: boolean;
  sourcePath?: string; // renderer-only; never included in ChatOfficeRef
}

workspaceApi.bind(sessionId: string, workspacePath: string): Promise<SessionWorkspaceBinding>;
workspaceApi.get(sessionId: string): Promise<SessionWorkspaceBinding | null>;
workspaceApi.revoke(sessionId: string): Promise<void>;
workspaceApi.search(sessionId: string, query: string): Promise<WorkspaceSearchResponse>;
```

- [ ] **Step 1: Write failing route and API client tests**

Backend tests must cover bind, get, revoke, invalid directory, traversal, and session mismatch. Vitest must assert the exact command names and camelCase-to-snake_case mapping.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_workspace_routes.py -q
cd /home/fz/project/sage && \
  npm run test:run -- src/shared/api/__tests__/workspaceApi.test.ts
```

Expected: backend routes return 404 and client command route assertions fail.

- [ ] **Step 3: Implement routes and IPC command map**

Use a dedicated router mounted under `/api/v1`; route handlers call `session_workspace.py`, never accept a `doc_id` from the URL without session validation, and return structured 400/404/403 errors. Add `workspace_bind`, `workspace_get`, `workspace_revoke`, and `workspace_search_files` to `COMMAND_ROUTES` with URL encoding for session and query values.

- [ ] **Step 4: Implement typed client and bridge**

`workspaceApi` uses existing `desktopInvoke` and `handleApiError`; `selectDirectory` remains the only native path picker. Do not expose a generic filesystem API.

- [ ] **Step 5: Run tests and type checks to verify GREEN**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_workspace_routes.py -q
cd /home/fz/project/sage && \
  npm run test:run -- src/shared/api/__tests__/workspaceApi.test.ts && \
  npm run typecheck:electron
```

Expected: PASS.

- [ ] **Step 6: Commit Workspace API**

```bash
cd /home/fz/project/sage && \
  git add backend/api/workspace_routes.py backend/main.py electron/commands.ts \
  electron/preload.ts src/shared/api/types.ts src/shared/api/workspaceApi.ts \
  src/shared/types/electron-api.d.ts backend/tests/integration/test_workspace_routes.py \
  src/shared/api/__tests__/workspaceApi.test.ts && \
  git commit -m "feat: expose session workspace binding API"
```

### Task 3: 将 `@` 搜索结果转换为 Office refs

**Files:**
- Modify: `backend/api/workspace_routes.py`。
- Modify: `src/shared/api/fileSearchClient.ts`。
- Modify: `src/features/chat/useAtFileQuery.ts`。
- Modify: `src/features/chat/AtFileMenu.tsx`。
- Create: `src/features/chat/__tests__/AtFileMenu.office.test.tsx`。
- Add route assertions to `backend/tests/integration/test_workspace_routes.py`。

**Interfaces:**

```typescript
interface ChatOfficeRef {
  docId: string;
  docType: 'ppt' | 'word' | 'excel';
  filename: string;
}

interface WorkspaceSearchResult {
  name: string;
  docType: 'ppt' | 'word' | 'excel' | null;
  docId: string | null;
  sizeBytes: number;
  needsImport: boolean;
  sourcePath?: string;
}
```

- [ ] **Step 1: Write failing search and selection tests**

Test that an already managed result selects a `ChatOfficeRef`, an unmanaged Office file is marked `needsImport`, non-Office files retain the existing text reference behavior, and `sourcePath` never appears in the `ChatOfficeRef` object.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/chat/__tests__/AtFileMenu.office.test.tsx
```

Expected: FAIL because the menu only inserts a raw path string and has no Office ref callback.

- [ ] **Step 3: Implement backend search**

Search only the active Workspace. Return managed Office rows from `office_documents`; for workspace files with supported extensions but no row, return `needsImport=true` and a renderer-only source path. Reject a query that tries to replace the session binding or search an outside root.

- [ ] **Step 4: Implement renderer selection state**

Extend `AtFileMenu` selection callback to return either `ChatOfficeRef` or the existing plain-file reference. Display `@filename`, but keep `docId` in component state. Do not put the local source path in the outgoing Chat request.

- [ ] **Step 5: Run GREEN tests and typecheck**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/chat/__tests__/AtFileMenu.office.test.tsx && \
  npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit Office ref search**

```bash
cd /home/fz/project/sage && \
  git add backend/api/workspace_routes.py backend/tests/integration/test_workspace_routes.py \
  src/shared/api/fileSearchClient.ts src/features/chat/useAtFileQuery.ts \
  src/features/chat/AtFileMenu.tsx src/features/chat/__tests__/AtFileMenu.office.test.tsx && \
  git commit -m "feat: resolve Chat Office references by document ID"
```

### Task 4: 扩展 Chat payload 和 Workspace 绑定 UI

**Files:**
- Modify: `backend/api/legacy_routes.py:89-112`。
- Modify: `src/shared/api/types.ts`。
- Modify: `src/shared/api/chatApi.ts:67-105`。
- Modify: `src/features/send-message/useChat.ts:92-413`。
- Modify: `src/widgets/chat/ChatInput.tsx:16-107,160-230`。
- Create: `src/widgets/chat/WorkspaceBindModal.tsx`。
- Modify: `src/pages/Chat.tsx:89-104`。
- Create: `src/widgets/chat/__tests__/WorkspaceBindModal.test.tsx`。
- Add focused tests for `ChatInput` and `useChat` payloads。

**Interfaces:**

```python
class ChatOfficeRef(BaseModel):
    doc_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    doc_type: Literal['ppt', 'word', 'excel']
    filename: str = Field(min_length=1, max_length=255)

class ChatRequest(BaseModel):
    session_id: str
    message: str
    office_refs: list[ChatOfficeRef] = Field(default_factory=list)
    # existing provider/model fields remain unchanged
```

```typescript
chatApi.chatStream(
  sessionId: string,
  message: string,
  handlers: ChatStreamHandlers,
  config?: ChatConfig,
  options?: { officeRefs?: ChatOfficeRef[] },
): Promise<{ streamId: string; cancel: () => void }>;
```

- [ ] **Step 1: Write failing payload tests**

Assert that `officeRefs` becomes snake_case `office_refs`, invalid IDs are rejected by backend Pydantic, and sending a normal message without Office refs remains backward-compatible.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage && npm run test:run -- src/shared/api/__tests__/chatApi.office.test.ts
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_chat_office_read.py -q
```

Expected: FAIL because `ChatRequest` and `chatStream` do not accept Office refs.

- [ ] **Step 3: Implement typed request plumbing**

Add `ChatOfficeRef` to backend and shared types, extend `ChatRequest`, `chatApi.chatStream`, `useChat.sendMessage`, `ChatInput.onSend`, and the `Chat.tsx` callback. Preserve existing knowledge refs, images, and non-Office attachments.

- [ ] **Step 4: Add WorkspaceBindModal**

When a user attempts an Office `@` selection or Office drop with no active binding, call `window.electronAPI.selectDirectory({ intent: 'open' })`, then `workspaceApi.bind(sessionId, selectedPath)`. Cancel leaves the message unsent and does not create a binding.

- [ ] **Step 5: Run GREEN tests and frontend gates**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/shared/api/__tests__/chatApi.office.test.ts \
  src/widgets/chat/__tests__/WorkspaceBindModal.test.tsx && \
  npm run typecheck
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_chat_office_read.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit ChatOfficeRef and binding UI**

```bash
cd /home/fz/project/sage && \
  git add backend/api/legacy_routes.py src/shared/api/types.ts \
  src/shared/api/chatApi.ts src/features/send-message/useChat.ts \
  src/widgets/chat/ChatInput.tsx src/widgets/chat/WorkspaceBindModal.tsx \
  src/pages/Chat.tsx src/widgets/chat/__tests__ && \
  git commit -m "feat: attach Office refs to Chat messages"
```

### Task 5: 引入 request-scoped ToolExecutionContext

**Files:**
- Create: `backend/tools/context.py`。
- Modify: `backend/tools/registry.py:90-106`。
- Modify: `backend/core/legacy/agent.py:449-609,648-667`。
- Modify: `backend/api/legacy_routes.py:1017-1061`。
- Create: `backend/tests/unit/tools/test_tool_context.py`。
- Add context cases to `backend/tests/integration/test_chat_office_read.py`。

**Interfaces:**

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    stream_id: str
    workspace_path: Path | None
    office_doc_scope: frozenset[str]

_context: ContextVar[ToolExecutionContext | None]

def current_tool_context() -> ToolExecutionContext | None:
    raise NotImplementedError
```

```python
class ToolRegistry:
    def get_schemas_for_llm(
        self,
        context: ToolExecutionContext | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def execute_with_context(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        raise NotImplementedError
```

- [ ] **Step 1: Write failing context and schema-filter tests**

Test that context is isolated between async tasks, no Workspace omits tools whose names start with `office_`, and a bound Workspace includes them. Test that `execute_with_context` passes context only through the request scope and does not mutate the registry’s singleton tools.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/tools/test_tool_context.py -q
```

Expected: FAIL because the context module and registry APIs are absent.

- [ ] **Step 3: Implement contextvar and registry methods**

Add a frozen dataclass and `ContextVar`. Extend registry schema filtering by an explicit `context`; retain the existing `get_schemas_for_llm()` behavior for non-Office callers. `execute_with_context` calls existing `tool.execute(**arguments)` after setting the context for the duration of the call and resets it in `finally`.

- [ ] **Step 4: Thread context through legacy run_loop**

Extend `SageAgent.run_loop(messages, max_iterations=None, llm_config=None, tool_context=None)`, call `get_available_tools(tool_context)` before each LLM call, and replace `tool.execute(**args)` with `registry.execute_with_context(tc.name, args, tool_context)`. Restore no global Agent/registry state after the run.

- [ ] **Step 5: Build context in chat_stream producer**

Load `get_active_workspace` using `data.session_id`, validate each `data.office_refs` against that Workspace, query all non-archived document IDs in the bound Workspace for `office_doc_scope`, create `ToolExecutionContext(session_id, stream_id, workspace_path, office_doc_scope)`, and pass it to `agent.run_loop`. Add a small system prompt line saying Office tools are unavailable until a Workspace is bound.

- [ ] **Step 6: Run GREEN context and chat tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/tools/test_tool_context.py tests/integration/test_chat_office_read.py -q
```

Expected: PASS; a session without binding cannot expose or execute Office tools.

- [ ] **Step 7: Commit request-scoped tool context**

```bash
cd /home/fz/project/sage && \
  git add backend/tools/context.py backend/tools/registry.py \
  backend/core/legacy/agent.py backend/api/legacy_routes.py \
  backend/tests/unit/tools/test_tool_context.py backend/tests/integration/test_chat_office_read.py && \
  git commit -m "feat: add session-scoped Chat tool context"
```

### Task 6: 实现 OfficeToolService 和只读 tools

**Files:**
- Create: `backend/office/tool_service.py`。
- Create: `backend/tools/office_tool.py`。
- Modify: `backend/tools/__init__.py:20-47`。
- Modify: `backend/office/storage.py` to add the session-scoped lookup helper `get_document_for_session` defined in Task 1。
- Create: `backend/tests/unit/office/test_tool_service_read.py`。
- Create: `backend/tests/unit/tools/test_office_tools.py`。

**Interfaces:**

```python
class OfficeToolService:
    def list(
        self,
        context: ToolExecutionContext,
        query: str | None = None,
        doc_type: OfficeDocType | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def read(
        self,
        context: ToolExecutionContext,
        doc_id: str,
        section: Literal['summary', 'head', 'all'] = 'summary',
    ) -> dict[str, Any]:
        raise NotImplementedError
```

```python
class OfficeListTool(BaseTool):
    name = 'office_list'

class OfficeReadTool(BaseTool):
    name = 'office_read'
```

- [ ] **Step 1: Write service authorization tests**

Test list filters, limit bounds, query matching, read summary/head/all, missing doc, archived doc, foreign session doc, and path traversal supplied as `doc_id`.

- [ ] **Step 2: Write tool schema/execute tests**

Assert schemas contain `doc_id` but never `file_path` or `workspace_path`; execute with a context returns serializable JSON; invalid tool args return `ToolResult(success=False, error='office_access_denied')` without leaking absolute paths.

- [ ] **Step 3: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_tool_service_read.py tests/unit/tools/test_office_tools.py -q
```

Expected: FAIL because the service and tool wrappers are absent.

- [ ] **Step 4: Implement session/doc_id authorization**

Use `get_active_workspace` and `get_document_for_session` for every operation. Reconstruct the managed path through M0 `document_path`; never concatenate a user-provided path. Apply `limit <= 100`, output-size truncation, and section selection before returning content.

- [ ] **Step 5: Implement read-only tool schemas and registration**

`OfficeListTool` and `OfficeReadTool` obtain the current context from `current_tool_context()`, reject missing context, call `OfficeToolService`, and return `ToolResult`. Register them in `register_all_tools`; keep schemas hidden unless context has an active Workspace.

- [ ] **Step 6: Run GREEN tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_tool_service_read.py tests/unit/tools/test_office_tools.py \
  tests/unit/tools/test_tool_context.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit read-only Office tools**

```bash
cd /home/fz/project/sage && \
  git add backend/office/tool_service.py backend/tools/office_tool.py \
  backend/tools/__init__.py backend/office/storage.py \
  backend/tests/unit/office/test_tool_service_read.py \
  backend/tests/unit/tools/test_office_tools.py && \
  git commit -m "feat: add Chat Office list and read tools"
```

### Task 7: M2 Chat read integration and E2E

**Files:**
- Modify: `backend/api/legacy_routes.py:1033-1053` — include validated Office refs in user context and operation summaries。
- Modify: `backend/data/message_repo.py` only if a compact tool summary field is required by existing persistence API。
- Modify: `src/features/send-message/useChat.ts:280-389` — render Office tool calls/results with doc IDs。
- Create: `backend/tests/integration/test_chat_office_read.py` complete mock LLM flows。
- Create: `tests/e2e/chat-office-read.spec.ts`。

- [ ] **Step 1: Write failing legacy Chat integration tests**

Mock `LLMClient.chat` to return `office_list`, then `office_read`, then a final text response. Assert the stream emits `acting`, `observing`, and `done`; the tool result is available to the next LLM call; a session without binding cannot call the tool; `office_refs` are validated before the LLM starts.

- [ ] **Step 2: Run integration tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_chat_office_read.py -q
```

Expected: FAIL until `SageAgent` receives the context and Office tools are registered.

- [ ] **Step 3: Persist compact Office operation summaries**

After a successful list/read tool call, insert an `office_operation_log` row with `session_id`, `tool_name`, `doc_id` when applicable, bounded `summary_json`, and `outcome='success'`. On each new turn, load the most recent 10 summaries into a bounded system-context section; never inject full document contents.

- [ ] **Step 4: Render Office tool result cards**

Extend existing tool-call rendering to show filename, doc type, doc ID, and a “在文件管理中查看” action without exposing unrestricted filesystem paths. Keep generic tools unchanged.

- [ ] **Step 5: Add the Chat E2E flow**

Use the existing Electron/Playwright project setup and mock bridge only for file selection; assert the UI flow: bind Workspace → import/reference DOCX → send “读取并总结” → see Office tool event and final answer. Add a negative case where no Workspace produces a binding prompt instead of a tool call.

- [ ] **Step 6: Run all M1–M2 verification gates**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q --cov=backend/office --cov=backend/tools
cd /home/fz/project/sage && \
  npm run test:run && npm run typecheck && npm run typecheck:electron
cd /home/fz/project/sage && npx playwright test tests/e2e/chat-office-read.spec.ts
```

Expected: all tests pass, Office/tool source coverage is at least 80%, and no modified production file contains `console.log`.

- [ ] **Step 7: Commit M1–M2 completion**

```bash
cd /home/fz/project/sage && \
  git add backend src electron tests/e2e/chat-office-read.spec.ts && \
  git commit -m "feat: connect Office read tools to Chat"
```

## M1–M2 Completion Gate

M1–M2 is complete only when a user can bind a Workspace, import or select a managed Office document through Chat, ask a natural-language read/list question, observe the actual legacy `SageAgent` tool call, receive a final answer based on the structured Office result, and cannot make the tool access a different Workspace or arbitrary path. M3 may start only after this flow and its negative security cases pass.
