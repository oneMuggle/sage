# Win7 与主分支平台能力修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在真实 Win7 安装包可稳定启动的前提下，修复记忆、流式 UI、LM Studio、工具、Office、知识库、会话摘要、时区和 workspace settings 的跨分支契约问题。

**Architecture:** 先修复 packaged Electron/backend 的单实例、单 child、readiness、命令 manifest、TLS、编码和 build provenance，再修复业务工具契约。记忆、模型和 UI 采用最小局部修改；Office/RAG 复用现有 workspace binding、ToolPolicy 和 reader；摘要与 workspace settings 使用明确持久化模型，不把临时内存字段当作 API 契约。所有可移植提交在 `main` feature 分支完成，Win7 Python 3.8/Pydantic 1 适配以独立提交 cherry-pick 到 `release/win7`。

**Tech Stack:** Electron 21.4.4, React, TypeScript, Vite, FastAPI, Python 3.11 (`sage-backend`), Python 3.8/Pydantic 1 (`sage-backend-py38`), SQLite, pytest, Vitest, Playwright Electron, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-win7-parity-platform-fixes-design.md`

## Global Constraints

- `main` 使用 Python 3.11/Pydantic 2；`release/win7` 使用 Python 3.8/Pydantic 1；代码避免 PEP 604、`zip(strict=)` 等 Win7 不支持语法。
- 所有后端 Python 测试必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python` 或项目规定的 `sage-backend` 环境；Win7 测试使用 `sage-backend-py38`。
- 不将 `release/win7` 合并到 `main`，不删除该分支；跨分支只使用 cherry-pick 并手动验证。
- 所有文件操作继续经过 path safety、ToolPolicy、workspace binding 和 generation 检查；工具输出不得返回绝对 workspace path。
- TLS 验证始终开启；不得以关闭证书验证规避 CA 问题。
- 所有机器可读日志使用 UTC；用户界面使用 IANA timezone formatter，默认 `Asia/Shanghai`。
- 每个任务遵循 RED → GREEN → IMPROVE，并以独立 conventional commit 结束。
- 本计划不实现 Office edit/version/archive/restore，不重写 Wiki 向量库/RRF，不把 `memory_search` 冒充 RAG。

## File Map

### Packaged runtime
- Modify: `electron/main.ts` — Electron single-instance lock、backend supervisor generation/PID/ownership、ready/disconnect 生命周期。
- Modify: `electron/backendLauncher.ts` — bundled interpreter、working directory、package root 和 child launch env。
- Modify: `electron/invoke.ts`, `electron/commands.ts` — readiness gate、command manifest 和 IPC event/route 契约。
- Modify: `electron/doctor.ts`, `backend/cli/doctor.py` — bundled doctor 入口和可诊断输出。
- Modify: `backend/main.py`, `backend/api/llm_proxy_routes.py` — ownership health、CA/bootstrap、stream teardown。
- Modify: `scripts/bundle-python.ps1`, `.github/workflows/release-win7.yml`, build metadata files — bundled imports、CA/MCP manifest、build provenance。
- Test: `electron/__tests__/backendLauncher.test.ts`, `electron/__tests__/commands.test.ts`, new supervisor/IPC tests, `backend/tests/unit/cli/*`, `backend/tests/integration/test_lifespan_wiring.py`.

### Core business fixes
- Modify: `backend/tools/memory_tool.py`, `backend/memory/manager.py` — synchronous save and search API contract.
- Modify: `src/pages/Chat.tsx` and existing auto-scroll tests — sticky-bottom behavior.
- Modify: `src/entities/setting/types.ts`, `src/entities/setting/storage.ts`, `src/features/manage-endpoints/api.ts`, settings pages, `backend/data/settings_canonicalizer.py`, `backend/api/hex_routes.py`, `backend/api/legacy_routes.py` — protocol/timezone/schema parity.
- Modify: `backend/tools/file_tool.py`, `backend/tools/registry.py`, `backend/core/legacy/agent.py`, `backend/adapters/out/tool/inproc_adapter.py` — `list_dir` visibility/alias policy.

### Office, Wiki, summaries, workspace
- Modify: `backend/requirements-py38.txt`, `backend/requirements-bundled.txt` — compatible Office/MCP/CA dependency manifest.
- Modify: `backend/tools/office_create_tool.py`, `backend/office/storage.py`, `backend/office/tool_service.py`, `backend/api/office_routes.py` — create/list/read registration round-trip.
- Create/modify: `backend/tools/wiki_tool.py`, `backend/wiki/*`, `backend/api/wiki_routes.py` — workspace-scoped Wiki search/answer and Office text ingest.
- Create/modify: `backend/data/session_summary_repo.py`, `backend/data/database.py`, `backend/memory/*`, `backend/api/legacy_routes.py`, `src/shared/api/memoryApi.ts`, `src/pages/Memory.tsx`, `src/widgets/memory/MemoryBrowser.tsx` — persistent session summaries and layered memory API/UI.
- Create/modify: `backend/data/workspace_settings_repo.py`, `backend/api/workspace_settings_routes.py`, settings models/client/UI — workspace settings and inheritance.

### Tests and docs
- Backend: `backend/tests/unit`, `backend/tests/integration`, `backend/tests/contract` additions per task.
- Frontend: existing `src/**/__tests__` suites and `tests/electron` contract/E2E fixtures.
- Docs: update `docs/technical/`, `docs/user-manual/`, and mark plan checklist as completed only after implementation.

---

### Task 0: Stabilize packaged startup and build provenance

**Files:**
- Modify: `electron/main.ts:1-270,900-950`
- Modify: `electron/backendLauncher.ts:1-180`
- Modify: `electron/invoke.ts:1-100`, `electron/commands.ts:1-80`
- Modify: `electron/doctor.ts`, `backend/cli/doctor.py`
- Modify: `backend/main.py` health/startup metadata and `scripts/bundle-python.ps1`
- Modify: `.github/workflows/release-win7.yml`, `.github/workflows/ci.yml`
- Test: `electron/__tests__/backendLauncher.test.ts`, new `electron/__tests__/backendSupervisor.test.ts`, `electron/__tests__/commands.test.ts`, `backend/tests/unit/cli/test_doctor.py`, `backend/tests/integration/test_lifespan_wiring.py`

**Interfaces:**
- Produces `BackendLaunchPlan { command: string; args: string[]; cwd: string; env: Record<string,string> }` with bundled interpreter and package root.
- Produces supervisor state keyed by `{ generation: number; pid: number; ownershipToken: string }`.
- `/health` returns a machine-readable build/ownership payload; Electron emits `backend:ready` only when PID, generation and token match.
- Produces a build manifest containing `buildId`, `commit`, `branch`, `version`, `electronVersion`, `pythonVersion`.

- [ ] **Step 1: Write failing launcher and doctor tests.**

```ts
it('packaged launch uses bundled Python and repository package root', () => {
  const plan = resolveBackendLaunchCommand({
    isPackaged: true,
    resourcesPath: 'C:/Program Files/Sage/resources',
    appPath: 'C:/Program Files/Sage/resources/app.asar',
    userDataPath: 'C:/Users/A/AppData/Roaming/Sage',
  });
  expect(plan.command).toBe('C:/Program Files/Sage/resources/python/python.exe');
  expect(plan.args).toEqual(['-m', 'backend.main']);
  expect(plan.env.PYTHONPATH).toContain('C:/Program Files/Sage/resources/backend');
});
```

```python
def test_doctor_uses_bundled_interpreter_and_reports_package_root(tmp_path):
    result = run_doctor(interpreter=tmp_path / "python.exe", package_root=tmp_path / "backend")
    assert result.interpreter == str(tmp_path / "python.exe")
    assert result.package_root == str(tmp_path / "backend")
    assert result.import_backend is True
```

- [ ] **Step 2: Run the focused tests and verify RED.**

Run: `npm exec vitest run electron/__tests__/backendLauncher.test.ts electron/__tests__/backendSupervisor.test.ts` and `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli/test_doctor.py -q`

Expected: the new supervisor/provenance assertions fail because launch readiness is currently port-based and doctor can use PATH Python.

- [ ] **Step 3: Write minimal single-instance and generation-guarded supervisor code.**

Implement in `electron/main.ts`:

```ts
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
  return;
}

interface BackendGeneration {
  generation: number;
  pid: number;
  ownershipToken: string;
}
```

Guard every spawn, health result, exit callback, restart timer, orphan kill, and ready event with the current generation. Never start a second child while one is `starting`, `ready`, or `stopping`; wait for process exit and port release before retrying.

- [ ] **Step 4: Make doctor and health use bundled runtime metadata.**

Pass the same `command`, `cwd`, `PYTHONPATH`, `SAGE_BUILD_ID`, and `SAGE_BACKEND_OWNERSHIP_TOKEN` to doctor and backend. Extend `/health` to return a synthetic shape such as:

```json
{"status":"ok","buildId":"redacted-build","pid":1234,"ownershipToken":"redacted-token"}
```

The Electron probe must reject a healthy response with a stale PID/token.

- [ ] **Step 5: Add manifest parity and readiness gating.**

Define one generated/static manifest consumed by Electron and frontend tests. Validate that every frontend `invoke()` command is in `COMMAND_ROUTES`; queue initial settings/session/theme requests until `backend:ready`; consume `backend:disconnected` and `backend:reconnected` in the renderer instead of logging them as unknown events.

- [ ] **Step 6: Add UTF-8 and UTC build diagnostics.**

Decode child stdout/stderr as UTF-8 with an escaped-byte fallback, add `buildId` to Electron/backend logs, and emit only UTC ISO timestamps from machine-readable log envelopes.

- [ ] **Step 7: Run the green suite.**

Run: `npm exec vitest run electron/__tests__/backendLauncher.test.ts electron/__tests__/backendSupervisor.test.ts electron/__tests__/commands.test.ts`; `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli backend/tests/integration/test_lifespan_wiring.py -q`.

Expected: PASS, including stale-generation events being ignored and duplicate Electron launch being rejected.

- [ ] **Step 8: Commit.**

```bash
git add electron backend/cli backend/main.py scripts/bundle-python.ps1 .github/workflows electron/__tests__ backend/tests
git commit -m "fix(win7): stabilize packaged backend lifecycle"
```

### Task 1: Fix settings schema, TLS/CA, model identity, and LM Studio

**Files:**
- Modify: `src/entities/setting/types.ts:18-155`, `src/entities/setting/storage.ts`
- Modify: `src/features/manage-endpoints/api.ts`, `src/pages/settings/EndpointsTab.tsx`
- Modify: `backend/data/settings_canonicalizer.py`, `backend/api/hex_routes.py`, `backend/api/legacy_routes.py`
- Modify: `backend/api/llm_proxy_routes.py`, `backend/core/legacy/llm_client.py`, `backend/adapters/out/llm/openai.py`
- Modify: `backend/main.py`, `scripts/bundle-python.ps1`, `backend/requirements-py38.txt`, `backend/requirements-bundled.txt`
- Test: `src/features/manage-endpoints/__tests__/api.test.ts`, settings schema tests, `backend/tests/unit/test_llm_proxy_url.py`, `backend/tests/integration/test_llm_proxy_routes.py`, new CA/model contract tests

**Interfaces:**
- `EndpointConfig.protocol: 'openai-compatible' | 'anthropic' | 'gemini' | 'ollama'` with migration default `openai-compatible` for unknown existing endpoints.
- `EndpointConfig.modelId` is an ID; `localModelPath` is separate and platform-validated.
- `AppSettings.timezone` defaults to `Asia/Shanghai` and is validated as an IANA timezone.
- `build_upstream_url()` preserves one `/v1` segment and proxy TLS always verifies certificates.

- [ ] **Step 1: Add failing tests for LM Studio and settings migration.**

```ts
it('discovers an OpenAI-compatible LM Studio endpoint without an API key', async () => {
  mockFetchModelsResponse([{ id: 'qwen2.5-7b-instruct' }]);
  await expect(fetchModels('http://127.0.0.1:1234/v1', '')).resolves.toEqual([
    { id: 'qwen2.5-7b-instruct' },
  ]);
  expect(lastRequest.headers.get('Authorization')).toBeNull();
});
```

```python
def test_settings_migrates_legacy_snake_case_and_rejects_invalid_timezone(client):
    response = client.put('/api/v1/settings', json={'timezone': 'Asia/Shanghai'})
    assert response.status_code == 200
    assert client.put('/api/v1/settings', json={'timezone': 'Not/AZone'}).status_code == 422
```

- [ ] **Step 2: Run focused tests and verify RED.**

Run: `npm exec vitest run src/features/manage-endpoints/__tests__/api.test.ts src/entities/setting/__tests__`; `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_proxy_url.py backend/tests/integration/test_llm_proxy_routes.py -q`.

Expected: missing explicit protocol/timezone and CA/model assertions fail.

- [ ] **Step 3: Implement canonical endpoint/model and timezone schema.**

Add protocol/model identity fields to TypeScript defaults, deep merge, reset, canonicalizer, legacy/hex settings validators, and `GeneralTab`/`EndpointsTab`. Normalize a base URL with one `/v1`; reject platform-incompatible local paths; default unknown old endpoints to `openai-compatible`.

- [ ] **Step 4: Implement CA bootstrap and structured TLS diagnostics.**

Use bundled certifi path for httpx requests without disabling verification. Include a redacted error code such as `ca_bundle_unavailable` or `tls_certificate_failed`; do not include API keys or full credentials in logs.

- [ ] **Step 5: Add LM Studio mock and streaming tests.**

Cover `/v1/models`, non-streaming `/v1/chat/completions`, SSE `data:` chunks, empty API key, base URL already ending `/v1`, and no duplicate `/v1/v1`.

- [ ] **Step 6: Run green tests and commit.**

Run: `npm exec vitest run src/features/manage-endpoints src/entities/setting`; `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_proxy_url.py backend/tests/integration/test_llm_proxy_routes.py backend/tests/integration/test_settings_endpoint.py backend/tests/integration/test_settings_route_hex.py backend/tests/integration/test_settings_route_legacy.py -q`.

```bash
git add src backend scripts/bundle-python.ps1 backend/requirements-*.txt
git commit -m "fix: align settings and OpenAI-compatible endpoint contracts"
```

### Task 2: Fix memory tools and sticky-bottom streaming UX

**Files:**
- Modify: `backend/tools/memory_tool.py:47-171`, `backend/memory/manager.py:75-366`
- Modify: `backend/api/legacy_routes.py:2510-2587`, `src/shared/api/memoryApi.ts`
- Modify: `src/pages/Chat.tsx:65-82`
- Test: `backend/tests/unit/test_memory_tool.py`, new real-manager contract tests, memory route tests, `src/pages/__tests__/Chat.auto-scroll.test.tsx`

**Interfaces:**
- `MemorySaveTool.execute()` calls synchronous `MemoryManager.memorize(content, memory_type, importance, tags, session_id)` and returns the actual ID.
- `MemorySearchTool.execute()` calls `MemoryManager.search_memories(query, memory_type=None, limit=20)`; `all` maps to `None`.
- `formatMemoryList(page, pageSize, type, sessionId?)` returns explicit layer/source metadata.
- Chat scrolling uses a fixed `BOTTOM_THRESHOLD_PX` and only follows if the user was at bottom before the update.

- [ ] **Step 1: Replace fake-contract tests with failing production-contract tests.**

```python
def test_memory_save_tool_uses_memorize_without_running_event_loop(real_memory_manager):
    result = MemorySaveTool(memory=real_memory_manager).execute(
        content='user prefers UTC+8', memory_type='episodic', importance=5, tags=[]
    )
    assert result.success is True
    assert result.output


def test_memory_search_tool_calls_search_memories_not_remember(memory_manager_spy):
    MemorySearchTool(memory=memory_manager_spy).execute(query='UTC', memory_type='all', limit=5)
    memory_manager_spy.search_memories.assert_called_once_with('UTC', None, 5)
    memory_manager_spy.remember.assert_not_called()
```

```tsx
it('does not take focus from history while a token arrives', async () => {
  setScrollMetrics({ scrollTop: 120, clientHeight: 400, scrollHeight: 1000 });
  render(<Chat />);
  fireEvent.scroll(screen.getByTestId('chat-scroll-container'));
  appendStreamingContent('next token');
  await waitFor(() => expect(scrollContainer.scrollTop).toBe(120));
});
```

- [ ] **Step 2: Run RED tests.**

Run the exact memory and auto-scroll test files. Expected: save attempts to await a string, search passes `query` to `remember`, and off-bottom scroll jumps to `scrollHeight`.

- [ ] **Step 3: Implement memory tool contract.**

Remove `new_event_loop()`/`run_until_complete()` from `MemorySaveTool`; call `memorize()` directly. Replace search call with `search_memories()`, normalize `all`, validate limits, and preserve structured error envelopes. Do not change the public synchronous `remember()` compatibility method unless a test proves it is necessary.

- [ ] **Step 4: Fix memory listing pagination/layer metadata.**

Apply `offset=(page-1)*page_size`, merge working/episodic/semantic according to the requested type, and return `memory_type`, `source`, `session_id`, and summary metadata. Keep legacy response compatibility where existing frontend code requires it.

- [ ] **Step 5: Implement sticky-bottom scrolling.**

Track `wasAtBottom` from `scrollHeight - clientHeight - scrollTop <= BOTTOM_THRESHOLD_PX`; update it in the scroll listener. On content changes, call `scrollTo({ top: scrollHeight })` only when `wasAtBottom`; expose an accessible “back to latest” button when false. On sending a new message, force one explicit scroll.

- [ ] **Step 6: Run green tests and commit.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_tool.py backend/tests/integration/test_routes_memory.py backend/tests/api/test_memory_endpoints.py -q`; `npm exec vitest run src/pages/__tests__/Chat.auto-scroll.test.tsx src/features/send-message/__tests__`.

```bash
git add backend/tools/memory_tool.py backend/memory backend/api src/shared/api/memoryApi.ts src/pages/Chat.tsx src/pages/__tests__/Chat.auto-scroll.test.tsx
git commit -m "fix: correct memory tool contracts and stream scrolling"
```

### Task 3: Complete list_dir, Office round-trip, and Agent Wiki/RAG access

**Files:**
- Modify: `backend/tools/file_tool.py`, `backend/tools/registry.py`, `backend/tools/__init__.py`, `backend/core/legacy/agent.py`, `backend/adapters/out/tool/inproc_adapter.py`
- Modify: `backend/requirements-py38.txt`, `backend/requirements-bundled.txt`
- Modify: `backend/tools/office_create_tool.py`, `backend/office/storage.py`, `backend/office/tool_service.py`, `backend/api/office_routes.py`
- Create/modify: `backend/tools/wiki_tool.py`, `backend/wiki/ingest.py`, `backend/wiki/file_parser.py`, `backend/wiki/search.py`, `backend/wiki/chat.py`
- Test: `backend/tests/unit/test_agent_profile_wiring.py`, `backend/tests/unit/test_file_tool.py`, `backend/tests/unit/tools/test_office_tool.py`, `backend/tests/unit/tools/test_office_create_tool.py`, `backend/tests/integration/test_chat_office_tools.py`, `backend/tests/integration/test_wiki_chat_stream.py`, new Wiki tool/Office ingest contract tests

**Interfaces:**
- Canonical tool name remains `list_dir`; if compatibility is needed, registry maps `list-dir` to `list_dir` while audit output remains canonical.
- `office_create` returns `{document_id, doc_type, filename}` only after `office_documents` registration succeeds; failed registration removes generated file.
- `WikiSearchTool.execute(query, workspace_path, limit)` and `WikiAnswerTool.execute(query, workspace_path, max_context)` operate only within an authorized workspace context and return relative document IDs/paths.

- [ ] **Step 1: Write failing visibility and round-trip tests.**

```python
def test_all_agent_paths_expose_canonical_list_dir():
    for registry in (make_legacy_registry(), make_hex_registry(), make_profile_registry('primary')):
        assert 'list_dir' in registry.list_names()
        assert 'list-dir' not in registry.list_names()


def test_office_create_registers_for_list_and_read(tmp_path, session_binding, office_service, db):
    created = office_service.create(
        conn=db,
        session_id=session_binding.session_id,
        binding_generation=session_binding.generation,
        doc_type='word',
        title='round-trip',
        output_dir=str(tmp_path),
    )
    listed = office_service.list(
        conn=db,
        session_id=session_binding.session_id,
        binding_generation=session_binding.generation,
    )
    assert any(item['id'] == created['document_id'] for item in listed)
    read_result = office_service.read(
        conn=db,
        session_id=session_binding.session_id,
        binding_generation=session_binding.generation,
        doc_id=created['document_id'],
        section='all',
    )
    assert read_result['success'] is True
```

```python
def test_wiki_search_tool_never_leaves_bound_workspace(workspace, outside_file, wiki_tool):
    result = wiki_tool.execute(
        query='secret',
        workspace_path=str(workspace),
        limit=5,
    )
    assert outside_file.name not in json.dumps(result)
```

- [ ] **Step 2: Run RED tests.**

Run the focused file/Office/Wiki tests. Expected: at least one registry path is missing or Office create is not registered for the read service; no Wiki Agent tool exists.

- [ ] **Step 3: Normalize list_dir registry and alias policy.**

Verify default registration in legacy and hex paths, profile whitelist inclusion, and explicit rejection or mapping of `list-dir`. Keep file path safety and `max_result_items` unchanged.

- [ ] **Step 4: Complete Office create/list/read transaction.**

After generator success, insert the canonical document record in the same guarded operation. On DB failure or parser mismatch, delete the generated file and return a structured error. Add Win7-compatible imports and avoid Pydantic 2-only APIs in shared code.

- [ ] **Step 5: Add workspace-scoped Wiki Agent tools.**

Implement tool wrappers over existing token/vector/RRF services. Obtain workspace from `ToolExecutionContext`, reject missing/stale binding, cap query/context/output bytes, redact absolute paths, and return an explicit `embedding_fallback` status when vector search is unavailable.

- [ ] **Step 6: Add Office text ingest adapter and dependency manifest.**

Extract bounded text from DOCX/PPTX/XLSX through existing readers, then pass text to Wiki ingest. Do not pass binary bytes to `read_text()`. Pin Python 3.8-compatible Office dependencies in `requirements-py38.txt`; explicitly classify `mcp` and `hnswlib` as bundled/optional in the manifest.

- [ ] **Step 7: Run green tests and commit.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_file_tool.py backend/tests/unit/test_agent_profile_wiring.py backend/tests/unit/tools/test_office_tool.py backend/tests/unit/tools/test_office_create_tool.py backend/tests/integration/test_chat_office_tools.py backend/tests/integration/test_wiki_chat_stream.py -q`.

```bash
git add backend/tools backend/office backend/wiki backend/requirements-*.txt backend/tests
git commit -m "feat: expose workspace file office and wiki tools"
```

### Task 4: Persist session summaries and expose all memory layers

**Files:**
- Create: `backend/data/session_summary_repo.py`
- Modify: `backend/data/database.py`, `backend/memory/working.py`, `backend/memory/manager.py`, `backend/application/services/chat_service.py`, `backend/memory/async_extractor.py`
- Modify: `backend/api/legacy_routes.py`, `backend/api/hex_routes.py`
- Modify: `src/shared/api/memoryApi.ts`, `src/pages/Memory.tsx`, `src/widgets/memory/MemoryBrowser.tsx`
- Test: new `backend/tests/unit/test_session_summary_repo.py`, `backend/tests/integration/test_session_summary_api.py`, memory lifecycle/compaction tests, `src/pages/__tests__/Memory.test.tsx`, `src/widgets/memory/__tests__/MemoryBrowser.test.tsx`

**Interfaces:**
- `SessionSummaryRepository.create_pending(session_id, source_turn_id) -> SessionSummary`.
- `SessionSummaryRepository.mark_ready(summary_id, content, updated_at_ms) -> SessionSummary`.
- `SessionSummaryRepository.mark_failed(summary_id, error_code, updated_at_ms) -> SessionSummary`.
- `SessionSummaryRepository.list_by_session(session_id, limit, offset) -> Page[SessionSummary]`.
- Memory retrieval order is working context, current-session summaries, then episodic/semantic; no cross-session summary injection.

- [ ] **Step 1: Write failing persistence and isolation tests.**

```python
def test_summary_survives_restart_and_is_session_scoped(database):
    repo = SessionSummaryRepository(database)
    ready = repo.mark_ready(repo.create_pending('s1', 'turn-1').id, 'summary', now_ms=1,)
    assert repo.list_by_session('s1', 20, 0).items[0].content == 'summary'
    reopened = SessionSummaryRepository(reopen_database(database.path))
    assert reopened.list_by_session('s1', 20, 0).items[0].id == ready.id
    assert reopened.list_by_session('s2', 20, 0).items == []
```

```python
def test_summary_failure_is_visible_and_not_stored_as_fact(summary_service):
    summary = summary_service.generate_or_mark_failed('s1', 'turn-1', llm_error=True)
    assert summary.status == 'failed'
    assert memory_manager.search_memories('turn-1', memory_type='episodic', limit=20) == []
```

- [ ] **Step 2: Run RED tests.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_session_summary_repo.py backend/tests/integration/test_session_summary_api.py -q` and the existing memory lifecycle suite. Expected: repository/table/API are absent or summaries disappear after reopen.

- [ ] **Step 3: Add SQLite session_summaries schema and repository.**

Create the table with `id`, `session_id`, nullable `source_turn_id`, `content`, `status`, `error_code`, `created_at_ms`, and `updated_at_ms`; index `(session_id, updated_at_ms DESC)`. Keep all timestamps as UTC epoch milliseconds.

- [ ] **Step 4: Wire summary generation to compaction/async queue.**

At session-end or compaction, create pending, generate through the existing LLM client in the background queue, then mark ready/failed. A summary failure must not fail the chat response. Preserve current `working` clear and episodic behavior only as compatibility, but use the repository as the summary source of truth.

- [ ] **Step 5: Add API and frontend layer metadata.**

Expose session-scoped summary list and memory list with `memory_type`, `source`, `session_id`, `summary_id`, pagination totals, and explicit status. Add Memory page filters/cards for working, summary, episodic, semantic, and core; source click navigates to the originating session only when a valid session ID exists.

- [ ] **Step 6: Run green tests and commit.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_session_summary_repo.py backend/tests/integration/test_session_summary_api.py backend/tests/memory backend/tests/unit/test_context_compactor.py -q`; `npm exec vitest run src/pages/__tests__/Memory.test.tsx src/widgets/memory/__tests__/MemoryBrowser.test.tsx src/shared/api`.

```bash
git add backend/data backend/memory backend/application/services backend/api src/shared/api/memoryApi.ts src/pages/Memory.tsx src/widgets/memory/MemoryBrowser.tsx backend/tests src/**/__tests__
git commit -m "feat: persist and surface session summaries"
```

### Task 5: Add timezone and workspace settings

**Files:**
- Create: `backend/data/workspace_settings_repo.py`, `backend/api/workspace_settings_routes.py`
- Modify: `backend/data/database.py`, `backend/data/settings_canonicalizer.py`, `backend/api/legacy_routes.py`, `backend/api/hex_routes.py`
- Modify: `src/entities/setting/types.ts`, `src/entities/setting/storage.ts`, `src/shared/api/settingsClient.ts`, `src/pages/settings/GeneralTab.tsx`
- Create/modify: `src/shared/lib/time/formatInstant.ts`, `src/shared/api/workspaceSettingsApi.ts`, workspace settings UI
- Test: backend settings parity/route tests, `backend/tests/unit/test_workspace_settings_repo.py`, `backend/tests/integration/test_workspace_settings_routes.py`, `src/entities/setting/__tests__`, `src/shared/lib/time/__tests__/formatInstant.test.ts`, workspace UI tests

**Interfaces:**
- `validate_timezone(value: str) -> str` accepts IANA names through `zoneinfo.ZoneInfo` and rejects invalid values with a structured 422.
- `formatInstant(ms: number, timezone: string = 'Asia/Shanghai', locale?: string) -> string` always treats `ms` as UTC epoch milliseconds; invalid timezone falls back to UTC.
- `WorkspaceSettingsRepository.get(workspace_id) -> WorkspaceSettings | None`, `upsert(workspace_id, patch)`, `clear(workspace_id)`.
- Workspace settings routes resolve workspace identity from the active session binding, never from an arbitrary client path.

- [ ] **Step 1: Write failing timezone/workspace tests.**

```ts
it('formats a fixed instant in UTC+8 independent of host timezone', () => {
  expect(formatInstant(Date.UTC(2026, 0, 1, 0, 0), 'Asia/Shanghai', 'zh-CN'))
    .toContain('08:00');
});
```

```python
def test_workspace_settings_inherit_and_clear(client, bound_session):
    assert client.get(f'/api/v1/sessions/{bound_session}/workspace/settings').json()['settings'] is None
    client.patch(f'/api/v1/sessions/{bound_session}/workspace/settings', json={'timezone': 'Asia/Shanghai'})
    assert client.get(f'/api/v1/sessions/{bound_session}/workspace/settings').json()['settings']['timezone'] == 'Asia/Shanghai'
    client.delete(f'/api/v1/sessions/{bound_session}/workspace/settings')
    assert client.get(f'/api/v1/sessions/{bound_session}/workspace/settings').json()['settings'] is None
```

- [ ] **Step 2: Run RED tests.**

Run the focused backend and frontend timezone/workspace tests. Expected: no timezone field, formatter, workspace settings table, or session-scoped settings route exists.

- [ ] **Step 3: Add timezone field and canonicalization.**

Add `timezone: string` with default `Asia/Shanghai` to `AppSettings`, local cache merge/reset, settings client, legacy/hex schema and backend canonicalizer. Validate with `zoneinfo.ZoneInfo`; preserve old settings by migration default. Add GeneralTab searchable/selectable timezone control and current offset preview.

- [ ] **Step 4: Add UTC formatter and migrate user-facing displays.**

Implement `formatInstant()` using `Intl.DateTimeFormat` with explicit `timeZone`; migrate session, memory, Office and summary timestamps touched by this feature. Do not change storage values or parse them as local datetime.

- [ ] **Step 5: Add workspace settings persistence and routes.**

Create workspace settings table keyed by normalized workspace identity, with nullable override fields and `updated_at_ms`. Resolve identity from active `session_workspace_bindings`; enforce `session override > workspace > app > product default`; interpret JSON `null` as clear/inherit, not empty string.

- [ ] **Step 6: Add frontend API/UI and isolation tests.**

Add workspace settings client and controls to the existing workspace/settings surface. Test two sessions bound to different workspaces cannot read or mutate one another's settings, and clearing a workspace setting restores app timezone/model defaults.

- [ ] **Step 7: Run green tests and commit.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/contract/test_settings_schema_parity.py backend/tests/integration/test_settings_endpoint.py backend/tests/integration/test_settings_route_hex.py backend/tests/integration/test_settings_route_legacy.py backend/tests/unit/test_workspace_settings_repo.py backend/tests/integration/test_workspace_settings_routes.py -q`; `npm exec vitest run src/entities/setting src/shared/lib/time src/shared/api src/pages/settings src/features/workspace`.

```bash
git add backend/data backend/api backend/tests src/entities/setting src/shared/lib/time src/shared/api src/pages/settings src/features/workspace
git commit -m "feat: add timezone and workspace settings"
```

### Task 6: Main verification, Win7 cherry-pick, and documentation

**Files:**
- Modify: `docs/technical/README.md`, relevant technical chapters, `docs/user-manual/README.md`, relevant user chapters
- Modify: `docs/plans/2026-08-23-win7-parity-platform-fixes.md`
- Test: full targeted main suite, Win7 py38 suite, packaging smoke and release artifact checks

**Interfaces:**
- Consumes all task commits from the feature branch.
- Produces separate Win7 compatibility commits and a documented verification matrix.

- [ ] **Step 1: Run main branch validation.**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit backend/tests/integration backend/tests/contract -q`; `npm run typecheck`; `npm exec vitest run`; `npm run build`; `npx playwright test e2e/electron/smoke.spec.ts`.

Expected: all required checks pass; any pre-existing unrelated failure is recorded with its exact command and output rather than hidden.

- [ ] **Step 2: Review security and cross-language changes.**

Run the mandatory code review agents for Python, TypeScript, general quality and security. Specifically inspect path traversal, workspace binding authority, TLS verification, secrets in logs, subprocess ownership, and stale-generation event handling.

- [ ] **Step 3: Create Win7 compatibility cherry-pick branch.**

From updated `release/win7`, create a dedicated branch and cherry-pick only portable fixes. Adapt Pydantic 2 APIs (`model_dump`, `ConfigDict`) to Pydantic 1-compatible forms where shared code is touched; retain Win7-specific dependency pins and Electron 21 APIs.

- [ ] **Step 4: Run Win7 validation.**

Use `sage-backend-py38` for `cd backend && pytest --cov --cov-fail-under=80`, `ruff check backend/`, `npm run typecheck`, `npm exec vitest run`, `npm run electron:build`, and the Electron smoke test. Run a packaged launch canary verifying single-instance lock, doctor interpreter, backend ready ownership, settings GET, session creation, LM Studio mock, memory save/search, list_dir, Office round-trip, and shutdown.

- [ ] **Step 5: Update technical and user documentation.**

Document the runtime readiness state machine, build manifest, LM Studio setup, memory layers/summary behavior, Office/RAG scope, `Asia/Shanghai` default, timezone override, workspace settings inheritance, and Win7 release limitations. Remove the plan only after implementation is fully merged according to project documentation rules.

- [ ] **Step 6: Commit compatibility/docs changes.**

```bash
git add docs docs/plans/2026-08-23-win7-parity-platform-fixes.md
git commit -m "docs: document Win7 parity fixes and verification matrix"
```

## Self-Review Checklist

- [ ] Spec coverage: batch zero covers doctor, supervisor, single instance, IPC drift, settings drift, UTF-8, CA, MCP, model paths, Proactor teardown and build provenance.
- [ ] Spec coverage: batch one covers memory contracts, sticky-bottom, LM Studio, list_dir and schema migration.
- [ ] Spec coverage: batch two covers Win7 Office dependencies, list_dir visibility, Office create/list/read and Wiki/RAG tools/Office ingest.
- [ ] Spec coverage: batch three covers persistent summaries, session isolation, API/UI layer metadata and queue failure states.
- [ ] Spec coverage: batch four covers UTC epoch-ms, `Asia/Shanghai`, IANA validation, formatter and workspace settings inheritance.
- [ ] Placeholder scan: the plan contains no unresolved placeholder instructions.
- [ ] All later task interfaces use the exact names defined in earlier tasks.
- [ ] Every task has RED, GREEN, verification and commit steps.
