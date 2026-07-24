# Office M3-M5 Chat Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成 M1–M2 只读 Chat 闭环的基础上，实现 Office create/edit/archive/restore、派生版本、真实 diff、approval stream、管理视图和最终安全验收。

**Architecture:** `OfficeToolService` 扩展为 prepare/apply 两阶段，所有写操作先生成服务端 proposal，再由当前 legacy Chat stream 等待用户批准。Office adapter 只执行结构化 Word/PPT/Excel 操作并写入新 UUID 版本；parent 永不覆盖。M5 只定义未来 hex ChatService adapter 契约，不迁移当前 Chat 主链。

**Tech Stack:** Python 3.11 (`sage-backend` conda env)、FastAPI、Pydantic 2、SQLite/WAL、python-pptx 0.6.23、python-docx 1.1.2、openpyxl 3.1.5、legacy SageAgent ReAct/NDJSON、Electron IPC、React/TypeScript、Vitest、Playwright。

## Global Constraints

- M0 和 M1–M2 必须已完成、测试全绿且工作区干净。
- 后端命令使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。
- LLM tools 只接受 `doc_id`、结构化 spec 和结构化 operations，不接受路径/XML/Python/脚本。
- create/edit/archive/restore 全部需要 UI approval；list/read 不需要 approval。
- edit 始终生成新文档，`derived_from=parent_doc_id`，parent 文件不覆盖。
- delete 的对话语义是 archive 到 `.office-trash`，不提供 LLM 永久删除工具。
- proposal 绑定 `session_id`、`stream_id`、parent fingerprint，60 秒后 fail-closed。
- 文档和操作摘要限制大小；不把完整 Office 内容无限注入 Chat history/system prompt。
- Win7 只在 main 完成后另开 cherry-pick PR；本计划不修改 `backend/requirements-py38.txt`。

## File Map

### Backend domain / tools

- Modify: `backend/office/models.py` — typed edit operations、proposal、archive metadata。
- Create: `backend/office/proposals.py` — proposal model、fingerprint、TTL validation。
- Modify: `backend/office/tool_service.py` — create/edit/archive/restore prepare/apply。
- Modify: `backend/office/ppt.py` — structured PPT edit adapter。
- Modify: `backend/office/word.py` — structured DOCX edit adapter。
- Modify: `backend/office/excel.py` — structured XLSX edit adapter。
- Modify: `backend/tools/office_tool.py` — write tools and approval-aware interfaces。
- Modify: `backend/tools/registry.py` and `backend/tools/context.py` only if approval context needs propagation。
- Modify: `backend/data/database.py` — proposal/audit indexes and migration checks。
- Create: `backend/tests/unit/office/test_proposals.py`。
- Create: `backend/tests/unit/office/test_tool_service_write.py`。
- Create: `backend/tests/unit/office/test_office_edit_adapters.py`。
- Create: `backend/tests/unit/tools/test_office_write_tools.py`。

### Legacy Chat approval stream

- Create: `backend/core/legacy/approval.py` — `PendingApprovalStore`。
- Modify: `backend/core/legacy/agent_state.py` — `approval_required` event payload。
- Modify: `backend/core/legacy/agent.py:549-609` — prepare/wait/apply write tool flow。
- Modify: `backend/api/legacy_routes.py:960-1197` — approval endpoint and stream authorization。
- Modify: `electron/commands.ts:13-26` — approval command route。
- Modify: `src/shared/api/chatApi.ts` — approve/reject method。
- Modify: `src/shared/api/types.ts` — approval event/proposal types。
- Modify: `src/features/send-message/useChat.ts` — pending approval state and resume。
- Create: `src/widgets/chat/OfficeApprovalCard.tsx`。
- Create: `backend/tests/integration/test_chat_office_approval.py`。
- Create: `src/widgets/chat/__tests__/OfficeApprovalCard.test.tsx`。

### Office management UI / E2E / docs

- Modify: `src/pages/Office.tsx` — current session Workspace and management view。
- Modify: `src/features/office/OfficeDocumentList.tsx` — version tree/archive/restore/reference actions。
- Modify: `src/features/office/OfficePreviewPanel.tsx` — Chat ref action and version metadata。
- Remove composition use of: `src/features/office/OfficeGenerateForm.tsx` from `/office` page。
- Create: `src/features/office/__tests__/OfficeManagementView.test.tsx`。
- Create: `tests/e2e/chat-office-crud.spec.ts`。
- Modify: `.github/workflows/ci.yml` — M3–M5 targeted backend/frontend/E2E gates。
- Create: `backend/tests/contract/test_office_hex_adapter_contract.py`。
- Create: `docs/technical/33-office-phase1.md`。
- Create: `docs/user-manual/07-office.md`。
- Modify: `docs/technical/README.md`、`docs/user-manual/README.md`。
- Modify: `docs/plans/2026-07-16_office-features.md`。
- Modify: `docs/superpowers/specs/2026-07-23-office-phase1-hardening-design.md` only to retain its superseded pointer。

---

### Task 1: 定义结构化 edit operations、proposal 和 fingerprint

**Files:**
- Modify: `backend/office/models.py`。
- Create: `backend/office/proposals.py`。
- Modify: `backend/data/database.py` only for indexes/compatibility checks。
- Create: `backend/tests/unit/office/test_proposals.py`。

**Interfaces:**

```python
class WordReplaceParagraph(BaseModel):
    op: Literal['replace_paragraph']
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=10_000)

class WordAppendParagraph(BaseModel):
    op: Literal['append_paragraph']
    text: str = Field(min_length=1, max_length=10_000)
    heading: Literal['h1', 'h2', 'h3'] | None = None

class WordReplaceTableCell(BaseModel):
    op: Literal['replace_table_cell']
    table: int = Field(ge=0)
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    text: str = Field(max_length=10_000)

class PptReplaceSlideText(BaseModel):
    op: Literal['replace_slide_text']
    slide: int = Field(ge=0)
    old: str = Field(min_length=1, max_length=10_000)
    new: str = Field(max_length=10_000)

class PptAppendSlide(BaseModel):
    op: Literal['append_slide']
    title: str = Field(max_length=200)
    bullets: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=2_000)

class PptDeleteSlide(BaseModel):
    op: Literal['delete_slide']
    slide: int = Field(ge=0)

class ExcelSetCell(BaseModel):
    op: Literal['set_cell']
    sheet: str = Field(min_length=1, max_length=31)
    row: int = Field(ge=1)
    col: int = Field(ge=1)
    value: str = Field(max_length=10_000)

class ExcelSetRange(BaseModel):
    op: Literal['set_range']
    sheet: str = Field(min_length=1, max_length=31)
    start_row: int = Field(ge=1)
    start_col: int = Field(ge=1)
    values: list[list[str]] = Field(max_length=10_000)

class OfficeCreateRequest(BaseModel):
    doc_type: Literal['ppt', 'word', 'excel']
    filename: str = Field(min_length=1, max_length=200)
    spec: dict[str, object]

WordEditOperation = WordReplaceParagraph | WordAppendParagraph | WordReplaceTableCell
PptEditOperation = PptReplaceSlideText | PptAppendSlide | PptDeleteSlide
ExcelEditOperation = ExcelSetCell | ExcelSetRange
OfficeEditOperation = WordEditOperation | PptEditOperation | ExcelEditOperation

class OfficeProposal(BaseModel):
    proposal_id: str
    session_id: str
    stream_id: str
    tool_name: Literal['office_create', 'office_edit', 'office_archive', 'office_restore']
    doc_id: str | None
    parent_doc_id: str | None
    summary: str
    diff: dict[str, object]
    parent_fingerprint: str | None
    expires_at: int
```

- [ ] **Step 1: Write failing model and fingerprint tests**

Test valid/invalid operation discriminators, row/column/slide bounds, payload size limits, proposal expiration, proposal session mismatch, and a fingerprint changing when the managed file changes.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_proposals.py -q
```

Expected: FAIL because the operation and proposal models do not exist.

- [ ] **Step 3: Implement typed models and bounded fingerprint**

Use Pydantic discriminated unions for the operation list. Compute a fingerprint from file size, `st_mtime_ns`, and a bounded SHA-256 read of the managed file; never include raw document content in the proposal. `is_proposal_valid(proposal, session_id, now_ms)` must reject wrong session, expired timestamp, and missing required parent.

- [ ] **Step 4: Run GREEN tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_proposals.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit proposal contract**

```bash
cd /home/fz/project/sage && \
  git add backend/office/models.py backend/office/proposals.py \
  backend/data/database.py backend/tests/unit/office/test_proposals.py && \
  git commit -m "feat: define Office edit proposals and version fingerprints"
```

### Task 2: 实现 Office create/edit service 和格式 adapter

**Files:**
- Modify: `backend/office/tool_service.py`。
- Modify: `backend/office/ppt.py:218-277`。
- Modify: `backend/office/word.py:196-249`。
- Modify: `backend/office/excel.py:195-242`。
- Create: `backend/tests/unit/office/test_office_edit_adapters.py`。
- Create: `backend/tests/unit/office/test_tool_service_write.py`。

**Interfaces:**

```python
class OfficeToolService:
    def prepare_create(
        self,
        context: ToolExecutionContext,
        request: OfficeCreateRequest,
    ) -> OfficeProposal:
        raise NotImplementedError

    def prepare_edit(
        self,
        context: ToolExecutionContext,
        doc_id: str,
        operations: list[OfficeEditOperation],
    ) -> OfficeProposal:
        raise NotImplementedError

    def apply_create(self, proposal: OfficeProposal) -> OfficeDocumentSummary:
        raise NotImplementedError

    def apply_edit(self, proposal: OfficeProposal) -> OfficeDocumentSummary:
        raise NotImplementedError
```

Format adapter functions:

```python
def edit_ppt(
    source: Path,
    destination: Path,
    operations: list[PptEditOperation],
) -> None:
    raise NotImplementedError

def edit_docx(
    source: Path,
    destination: Path,
    operations: list[WordEditOperation],
) -> None:
    raise NotImplementedError

def edit_xlsx(
    source: Path,
    destination: Path,
    operations: list[ExcelEditOperation],
) -> None:
    raise NotImplementedError
```

- [ ] **Step 1: Write failing adapter tests**

Build fixtures with the existing Office test helpers and assert:

- Word paragraph replacement/append/table cell replacement;
- PPT slide text replacement, append, delete;
- Excel cell/range/sheet operations;
- unsupported index/table/sheet produces a typed failure;
- source checksum remains unchanged;
- destination can be reopened by the corresponding reader.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_office_edit_adapters.py tests/unit/office/test_tool_service_write.py -q
```

Expected: FAIL because the edit functions and service prepare/apply methods are absent.

- [ ] **Step 3: Implement non-destructive format adapters**

Load each source with its existing library, apply only the typed operations, save to a new managed UUID directory, and never call `save` on the parent path. Reject ambiguous text replacement unless exactly one target matches the specified slide/paragraph scope. Use existing Pydantic limits for slides, paragraphs, rows, and cells.

- [ ] **Step 4: Implement create preparation/application**

Reuse existing `generate_ppt`, `generate_docx`, and `generate_xlsx` request models. `prepare_create` validates the spec and returns a proposal preview; `apply_create` generates a new document, saves `status='generated'`, and returns the summary.

- [ ] **Step 5: Implement edit preparation/application**

`prepare_edit` loads the parent by session/doc_id, calculates real old/new values and parent fingerprint, and returns a proposal without writing. `apply_edit` rechecks the fingerprint, writes the child, saves `status='edited'`, `derived_from=parent_id`, and rejects stale proposals.

- [ ] **Step 6: Run GREEN adapter/service tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_office_edit_adapters.py \
  tests/unit/office/test_tool_service_write.py \
  tests/unit/office/test_ppt.py tests/unit/office/test_word.py \
  tests/unit/office/test_excel.py -q
```

Expected: PASS, and every edited source remains byte-for-byte untouched at its original path.

- [ ] **Step 7: Commit non-destructive edit service**

```bash
cd /home/fz/project/sage && \
  git add backend/office/tool_service.py backend/office/ppt.py \
  backend/office/word.py backend/office/excel.py \
  backend/tests/unit/office/test_office_edit_adapters.py \
  backend/tests/unit/office/test_tool_service_write.py && \
  git commit -m "feat: generate non-destructive Office edit versions"
```

### Task 3: 实现 archive/restore 服务和 write tools

**Files:**
- Modify: `backend/office/tool_service.py`。
- Modify: `backend/office/storage.py`。
- Modify: `backend/tools/office_tool.py`。
- Modify: `backend/tools/__init__.py`。
- Create: `backend/tests/unit/tools/test_office_write_tools.py`。
- Extend: `backend/tests/unit/office/test_tool_service_write.py`。

**Interfaces:**

```python
class OfficeToolService:
    def prepare_archive(
        self,
        context: ToolExecutionContext,
        doc_id: str,
    ) -> OfficeProposal:
        raise NotImplementedError

    def prepare_restore(
        self,
        context: ToolExecutionContext,
        doc_id: str,
    ) -> OfficeProposal:
        raise NotImplementedError

    def apply_archive(self, proposal: OfficeProposal) -> OfficeDocumentSummary:
        raise NotImplementedError

    def apply_restore(self, proposal: OfficeProposal) -> OfficeDocumentSummary:
        raise NotImplementedError
```

Tools:

```text
office_create
office_edit
office_archive
office_restore
```

Approval-aware tool contract:

```python
class ApprovalAwareOfficeTool(Protocol):
    def prepare_for_approval(
        self,
        context: ToolExecutionContext,
        arguments: dict[str, object],
    ) -> OfficeProposal:
        raise NotImplementedError

    def apply_approved(self, proposal: OfficeProposal) -> ToolResult:
        raise NotImplementedError
```

The legacy Agent checks this protocol before calling normal `execute`; it never accepts fresh LLM arguments after approval.

- [ ] **Step 1: Write failing archive/restore and schema tests**

Assert archive moves the UUID directory to `.office-trash`, sets `archived_at`, hides the document from default list, and does not delete the source outside Workspace. Assert restore refuses a destination conflict and clears `archived_at` on success. Assert write tool schemas expose no filesystem path.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_tool_service_write.py \
  tests/unit/tools/test_office_write_tools.py -q
```

Expected: FAIL because archive/restore and write tool wrappers are absent.

- [ ] **Step 3: Implement archive and restore atomically enough for local SQLite/filesystem**

Validate the current session/doc_id, move the whole managed UUID directory with `shutil.move`, update `archived_at`, and keep the DB row if the filesystem move fails. Restore checks the destination does not exist before moving back. Do not add an LLM permanent-delete tool.

- [ ] **Step 4: Implement write tool prepare/apply wrappers**

Each write tool reads `current_tool_context()`, calls the matching `prepare_*` method, and returns an approval-required result containing only `proposal_id`, sanitized summary, and diff. The approved execution path accepts only a server-side proposal object, not fresh LLM arguments.

- [ ] **Step 5: Run GREEN tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_tool_service_write.py \
  tests/unit/tools/test_office_write_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit write tool wrappers**

```bash
cd /home/fz/project/sage && \
  git add backend/office/tool_service.py backend/office/storage.py \
  backend/tools/office_tool.py backend/tools/__init__.py \
  backend/tests/unit/office/test_tool_service_write.py \
  backend/tests/unit/tools/test_office_write_tools.py && \
  git commit -m "feat: add Office create archive and restore tools"
```

### Task 4: 实现 legacy approval store 和 approval_required stream

**Files:**
- Create: `backend/core/legacy/approval.py`。
- Modify: `backend/core/legacy/agent_state.py`。
- Modify: `backend/core/legacy/agent.py:549-609`。
- Modify: `backend/api/legacy_routes.py:960-1197`。
- Modify: `electron/commands.ts:13-26`。
- Create: `backend/tests/integration/test_chat_office_approval.py`。

**Interfaces:**

```python
@dataclass(frozen=True)
class ApprovalDecision:
    proposal_id: str
    session_id: str
    approved: bool
    decided_at: int

async def wait_for_decision(
    stream_id: str,
    proposal_id: str,
    session_id: str,
    timeout_seconds: float = 60.0,
) -> ApprovalDecision:
    raise NotImplementedError

async def decide(
    stream_id: str,
    proposal_id: str,
    session_id: str,
    approved: bool,
) -> bool:
    raise NotImplementedError
```

Endpoint:

```text
POST /api/v1/chat/stream/{stream_id}/approval
body: { proposal_id: string, approved: boolean }
response: { accepted: true }
```

- [ ] **Step 1: Write failing approval store tests**

Test approve, reject, timeout, wrong session, wrong stream, replay after consumption, and cancellation on stream shutdown. Assert no decision after TTL can resume an operation.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_chat_office_approval.py -q
```

Expected: FAIL because the store, event, and endpoint do not exist.

- [ ] **Step 3: Implement PendingApprovalStore**

Use an in-memory map of `stream_id + proposal_id` to an `asyncio.Future`, expire entries after 60 seconds, consume the entry once, and fail closed on timeout/cancel. Keep all proposal data server-side; the request only carries the opaque proposal ID.

- [ ] **Step 4: Add `approval_required` AgentEvent**

Extend the event model with `state='approval_required'`, `proposal_id`, operation summary, diff, and expiration. Do not include arbitrary source paths or raw document bodies in the event.

- [ ] **Step 5: Pause and resume the real legacy run_loop**

Before executing an approval-aware Office tool, call its prepare operation, emit `approval_required`, await `PendingApprovalStore`, return a rejected `ToolResult` on denial/timeout, or call `apply_*` using the stored proposal on approval. Append the resulting tool message so the existing ReAct loop can request the next LLM turn.

- [ ] **Step 6: Add session-authorized approval endpoint and command route**

Look up the stream entry’s session ID, compare it to the request session/proposal, call `approval_store.decide`, and return 403/404/409 for mismatches, missing streams, or consumed proposals. Add `approve_chat_tool` to `electron/commands.ts` with URL encoding and POST body forwarding.

- [ ] **Step 7: Run GREEN backend approval tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/integration/test_chat_office_approval.py \
  tests/integration/test_chat_office_read.py -q
```

Expected: PASS; reject, timeout, disconnect, and replay never write files.

- [ ] **Step 8: Commit approval stream**

```bash
cd /home/fz/project/sage && \
  git add backend/core/legacy/approval.py backend/core/legacy/agent_state.py \
  backend/core/legacy/agent.py backend/api/legacy_routes.py \
  electron/commands.ts backend/tests/integration/test_chat_office_approval.py && \
  git commit -m "feat: add approval stream for Chat Office writes"
```

### Task 5: 实现前端 approval card 和 Chat resume

**Files:**
- Modify: `src/shared/api/types.ts`。
- Modify: `src/shared/api/chatApi.ts`。
- Modify: `src/features/send-message/useChat.ts`。
- Create: `src/widgets/chat/OfficeApprovalCard.tsx`。
- Create: `src/widgets/chat/__tests__/OfficeApprovalCard.test.tsx`。
- Add event cases to existing Chat/useChat tests。

**Interfaces:**

```typescript
interface OfficeApprovalEvent {
  state: 'approval_required';
  streamId: string;
  proposalId: string;
  toolName: 'office_create' | 'office_edit' | 'office_archive' | 'office_restore';
  summary: string;
  diff: Record<string, unknown>;
  expiresAt: number;
}

chatApi.decideApproval(
  streamId: string,
  proposalId: string,
  approved: boolean,
): Promise<{ accepted: true }>;
```

- [ ] **Step 1: Write failing card and event tests**

Test that approval event creates a card, renders sanitized summary/diff, approve sends the exact stream/proposal IDs, reject sends false, expired cards disable both buttons, and duplicate clicks are ignored.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/widgets/chat/__tests__/OfficeApprovalCard.test.tsx
```

Expected: FAIL because the event type, API method, state handling, and card do not exist.

- [ ] **Step 3: Implement typed approval client and event state**

Extend `AgentEvent` union, handle `approval_required` in `useChat.onEvent`, retain pending proposal state while the stream remains active, and route approve/reject through `chatApi.decideApproval`. Keep the existing `onDone` behavior until the resumed stream emits done/failed.

- [ ] **Step 4: Implement accessible OfficeApprovalCard**

Use `role="dialog"`, a descriptive heading, text diff rows, explicit “批准” and “拒绝” buttons, disabled state after decision, and no raw absolute path. Render it inside the current message/tool-call area so the user sees which Chat operation is paused.

- [ ] **Step 5: Run GREEN frontend gates**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/widgets/chat/__tests__/OfficeApprovalCard.test.tsx && \
  npm run typecheck && npm run typecheck:electron
```

Expected: PASS.

- [ ] **Step 6: Commit approval UI**

```bash
cd /home/fz/project/sage && \
  git add src/shared/api/types.ts src/shared/api/chatApi.ts \
  src/features/send-message/useChat.ts src/widgets/chat/OfficeApprovalCard.tsx \
  src/widgets/chat/__tests__/OfficeApprovalCard.test.tsx && \
  git commit -m "feat: render Chat Office approval proposals"
```

### Task 6: 将 `/office` 降级为版本/回收管理视图

**Files:**
- Modify: `src/pages/Office.tsx`。
- Modify: `src/features/office/OfficeDocumentList.tsx`。
- Modify: `src/features/office/OfficePreviewPanel.tsx`。
- Remove composition use of: `src/features/office/OfficeGenerateForm.tsx` from `/office` page。
- Create: `src/features/office/__tests__/OfficeManagementView.test.tsx`。

- [ ] **Step 1: Write failing management-view tests**

Assert the page reads the current session Workspace binding instead of keeping an independent workspace state, hides the standalone generate form, renders parent/child versions, exposes archive/restore, and sends a selected `ChatOfficeRef` back to ChatInput.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/office/__tests__/OfficeManagementView.test.tsx
```

Expected: FAIL because the page still owns Workspace selection and composes the generator form.

- [ ] **Step 3: Wire page to session binding and document tree**

Use `workspaceApi.get(currentSessionId)`, list only that Workspace, group documents by `derived_from`, and place `archived_at` documents in a recoverable section. Keep import/preview and M0 open/save/show-folder actions.

- [ ] **Step 4: Add Chat reference action**

Add “引用到当前对话” to preview/list. Dispatch a `ChatOfficeRef` to the active ChatInput without exposing the managed absolute path to the Chat request.

- [ ] **Step 5: Remove standalone generation from composition**

Do not delete the generator backend; only remove `OfficeGenerateForm` from `/office`. `office_create` remains the Chat tool entry.

- [ ] **Step 6: Run GREEN frontend tests**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/office/__tests__/OfficeManagementView.test.tsx && \
  npm run typecheck && npm run typecheck:electron
```

Expected: PASS.

- [ ] **Step 7: Commit management view**

```bash
cd /home/fz/project/sage && \
  git add src/pages/Office.tsx src/features/office && \
  git commit -m "refactor: make Office page a Chat workspace manager"
```

### Task 7: 完成 Chat-native CRUD E2E、审计和文档

**Files:**
- Create: `tests/e2e/chat-office-crud.spec.ts`。
- Create: `backend/tests/contract/test_office_hex_adapter_contract.py`。
- Modify: `.github/workflows/ci.yml`。
- Create: `docs/technical/33-office-phase1.md`。
- Create: `docs/user-manual/07-office.md`。
- Modify: `docs/technical/README.md`、`docs/user-manual/README.md`。
- Modify: `docs/plans/2026-07-16_office-features.md`。
- Modify: `docs/superpowers/specs/2026-07-23-office-phase1-hardening-design.md` only to retain its superseded pointer。

- [ ] **Step 1: Write the failing full CRUD E2E**

Cover exactly:

```text
bind Workspace
→ import DOCX
→ Chat read/summarize
→ Chat edit request
→ inspect real diff
→ reject and assert source/DB unchanged
→ repeat and approve
→ assert child doc_id and derived_from
→ Chat list latest versions
→ Chat archive old version with confirmation
→ /office restore old version
```

Add negative cases: foreign-session doc ID, arbitrary path in tool args, timeout, stream disconnect, replayed approval, and Workspace revoke.

- [ ] **Step 2: Run E2E to verify RED**

```bash
cd /home/fz/project/sage && npx playwright test tests/e2e/chat-office-crud.spec.ts
```

Expected: FAIL until the complete Chat write flow and management view are connected.

- [ ] **Step 3: Add hex adapter contract without migrating Chat**

Create a contract test documenting that future adapter methods accept the same `OfficeToolService` signatures and `ToolExecutionContext`; assert no second Office implementation is introduced. Do not route `/api/v1/chat/stream` to hex in this task.

- [ ] **Step 4: Add CI gates**

Run moved backend tests, Office/Chat unit tests, Electron typecheck, frontend typecheck, and the targeted CRUD E2E in the existing CI projects. Keep Windows path canary and bundled `import backend.main` canary from M0.

- [ ] **Step 5: Perform security review**

Use the security-reviewer agent on the full diff. It must explicitly verify doc_id-only tool schemas, session Workspace join, proposal replay/TTL, archive path containment, parent immutability, approval fail-closed, error redaction, and no arbitrary shell/openPath path.

- [ ] **Step 6: Write technical documentation**

`docs/technical/33-office-phase1.md` must document OfficeToolService, session binding, managed paths, tool schemas, approval stream, versioning, archive/restore, limits, and Windows/bundled constraints. Update `docs/technical/README.md` table with a one-line entry.

- [ ] **Step 7: Write user documentation**

`docs/user-manual/07-office.md` must explain Chat import via `@`/drop, Workspace binding, natural-language list/read/create/edit/archive/restore, confirmation cards, versioning, recovery, supported formats, and explicit non-goals. Update `docs/user-manual/README.md` table.

- [ ] **Step 8: Update the old Office roadmap**

Mark the old Phase 1 standalone wording as superseded by M0–M4 Chat-native milestones; leave future template/chart/LLM roadmap sections accurate and incomplete. Keep `docs/superpowers/specs/2026-07-23-office-chat-native-crud-design.md` as the current design baseline and the prior hardening spec as superseded.

- [ ] **Step 9: Run final verification**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q --cov=backend --cov-report=term-missing
cd /home/fz/project/sage && \
  npm run test:run && npm run typecheck && npm run typecheck:electron && npm run build
cd /home/fz/project/sage && npx playwright test tests/e2e/chat-office-crud.spec.ts
```

Expected: all tests pass, Backend/Office/Chat coverage is at least 80%, Windows/bundled contracts pass, and no modified production file contains `console.log` or hardcoded secrets.

- [ ] **Step 10: Commit M3–M5 completion**

```bash
cd /home/fz/project/sage && \
  git add backend electron src tests/e2e .github/workflows/ci.yml \
  docs/technical docs/user-manual docs/plans/2026-07-16_office-features.md && \
  git commit -m "feat: complete Chat-native Office CRUD"
```

## M3–M5 Completion Gate

M3–M5 is complete only when Chat can create, structurally edit, archive, and restore Office documents through the real legacy SageAgent path; every write has a server-generated diff and user approval; edits generate children without changing parents; session isolation and proposal replay tests pass; `/office` is a management view; and the full Chat-native CRUD E2E succeeds.

## Handoff to Future Hex ChatService

The future adapter must consume these exact domain interfaces without reimplementing them:

```python
OfficeToolService.list(
    context: ToolExecutionContext,
    query: str | None = None,
    doc_type: OfficeDocType | None = None,
    include_archived: bool = False,
    limit: int = 20,
)
OfficeToolService.read(
    context: ToolExecutionContext,
    doc_id: str,
    section: Literal['summary', 'head', 'all'] = 'summary',
)
OfficeToolService.prepare_create(context: ToolExecutionContext, request: OfficeCreateRequest)
OfficeToolService.prepare_edit(
    context: ToolExecutionContext,
    doc_id: str,
    operations: list[OfficeEditOperation],
)
OfficeToolService.prepare_archive(context: ToolExecutionContext, doc_id: str)
OfficeToolService.prepare_restore(context: ToolExecutionContext, doc_id: str)
OfficeToolService.apply_create(proposal: OfficeProposal)
OfficeToolService.apply_edit(proposal: OfficeProposal)
OfficeToolService.apply_archive(proposal: OfficeProposal)
OfficeToolService.apply_restore(proposal: OfficeProposal)
```

The current implementation remains legacy-first until a separate migration plan explicitly covers hex ChatService ReAct continuation and approval integration.

## Final Delivery Sequence

1. Complete and review M0 plan.
2. Start M1–M2 only from M0 completion gate.
3. Start M3–M5 only from M1–M2 completion gate.
4. Run code review and security review after product code changes.
5. Run live Electron Chat-native smoke verification before any merge.
6. Create a separate Win7 cherry-pick plan after main is merged and release requirements are validated.
