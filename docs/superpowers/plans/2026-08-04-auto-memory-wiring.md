# Auto-Memory Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire sage's existing memory system so users can see, control, and trace auto-extracted memories via IPC + settings toggle + sidebar Memory page with click-to-trace UI.

**Architecture:** Wrap (not modify) the existing `MemoryManager` with a `MemoryLifecycleManager` exposing `on_turn_complete` / `on_session_end` / `on_pre_compress` hooks (Hermes-style). All memory writes route through a `HookRegistry` that fans out to an SSE endpoint + Electron IPC + Evolution tasks. UI side: Settings toggle → Sidebar Memory entry → 3-tab Memory page (all / user profile / session summary) with `source_turn_id` traceability.

**Tech Stack:** Python 3.11 (Py3.8 for win7 cherry-pick), FastAPI, SQLite + sqlite-vec + FTS5, asyncio, SSE (`StreamingResponse`), Electron 21.4.4, React + Vite, TypeScript, EventSource API, vitest, pytest, Playwright.

## Global Constraints

- Branch: `feat/auto-memory-wiring` (new, from `chore/win7-predev-prebuild` HEAD or `main`)
- Python deps: must run in conda env `sage-backend` (`/home/fz/anaconda3/envs/sage-backend/bin/python`)
- Test commands: `pytest` (Python) from `backend/`, `vitest` from project root
- Commit messages: Conventional Commits format (`feat:` / `fix:` / `chore:` / `test:` / `docs:`)
- All memory-related code MUST `try/except` and never raise into ChatService
- Default `auto_memory` = `True` (backward compatible)
- DB schema migrations MUST be idempotent (check column existence via `PRAGMA table_info`)
- SSE event source: `text/event-stream` with 15s heartbeat; queue `maxsize=100`
- Frontend IPC naming: snake_case in `electron/commands.ts`, camelCase in renderer

---

## Task 1: IPC Wiring (Gap D)

**Files:**
- Modify: `electron/commands.ts:33-260` (add 11 new entries in `COMMAND_ROUTES`)
- Modify: `electron/preload.ts:40-146` (add new method exposures)
- Modify: `electron/invoke.ts:50-80` (path-param substitution)
- Test: manual smoke (`electron/relay.ts` already forwards all `sage:invoke`)

**Interfaces:**
- Consumes: existing FastAPI endpoints at `/api/v1/memory/*`, `/api/v1/preferences/*`, `/api/v1/evolution/trigger`, `/api/v1/memory/events` (SSE — to be added in Task 6)
- Produces: 11 IPC commands callable from renderer via `electronAPI.invoke(cmd, args)`

- [ ] **Step 1: Add 11 memory cmd mappings to `electron/commands.ts`**

Open `electron/commands.ts`. Find the `COMMAND_ROUTES` object. Insert these entries after the existing `trigger_evolution` mapping (around line 124):

```typescript
  memory_search: 'GET /api/v1/memory/search',
  memory_save: 'POST /api/v1/memory/save',
  memory_list: 'GET /api/v1/memory/list',
  memory_delete: 'POST /api/v1/memory/delete',
  memory_get_auto: 'GET /api/v1/preferences/auto_memory',
  memory_set_auto: 'PUT /api/v1/preferences/auto_memory',
  memory_find_by_turn: 'GET /api/v1/memory/by-turn/{turn_id}',
  memory_get_profile: 'GET /api/v1/memory/profile',
  memory_get_summary: 'GET /api/v1/memory/summary/{session_id}',
```

The existing `trigger_evolution` and `get_memories` / `delete_memory` / `get_preference` / `set_preference` mappings stay unchanged.

- [ ] **Step 2: Add path-param helper support**

The current `invokeBackend` in `electron/invoke.ts:50-80` does NOT substitute `{turn_id}` / `{session_id}` placeholders. Open `electron/invoke.ts` and update the path-building logic. Find the section that constructs `path` from `route`:

```typescript
// Current: const path = route;  // doesn't substitute
// Change to:
let path = route;
const pathParams = args && typeof args === 'object' ? extractPathParams(route, args) : {};
for (const [k, v] of Object.entries(pathParams)) {
  path = path.replace(`{${k}}`, encodeURIComponent(String(v)));
}
```

Add `extractPathParams(route, args)` helper at top of `electron/invoke.ts`:

```typescript
function extractPathParams(route: string, args: Record<string, unknown>): Record<string, string> {
  const matches = route.match(/\{(\w+)\}/g) || [];
  const result: Record<string, string> = {};
  for (const m of matches) {
    const key = m.slice(1, -1);
    if (key in args) result[key] = String(args[key]);
  }
  return result;
}
```

Then remove those path params from the body sent to backend (existing `camelToSnakeKeys` will not strip them automatically — add filter):

```typescript
// After path extraction, strip path params from body:
if (pathParams && Object.keys(pathParams).length > 0) {
  for (const k of Object.keys(pathParams)) delete args[k];
}
```

- [ ] **Step 3: Expose new methods in `electron/preload.ts`**

Open `electron/preload.ts`. Find the `contextBridge.exposeInMainWorld('electronAPI', { ... })` block (around line 40-146). Add these methods after the existing `invoke` / `listen` block:

```typescript
  memory: {
    search: (args: { query: string; type?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_search', args }),
    save: (args: { content: string; importance?: number; category?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_save', args }),
    list: (args: { page?: number; page_size?: number; type?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_list', args }),
    delete: (args: { memory_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_delete', args }),
    getAutoMemory: () =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_auto', args: {} }),
    setAutoMemory: (args: { value: boolean }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_set_auto', args: { value: String(args.value) } }),
    findByTurn: (args: { turn_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_find_by_turn', args }),
    getProfile: () =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_profile', args: {} }),
    getSummary: (args: { session_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_summary', args }),
  },
```

Also add a type declaration at top of `preload.ts`:

```typescript
type MemoryApi = {
  search: (args: { query: string; type?: string }) => Promise<unknown>;
  save: (args: { content: string; importance?: number; category?: string }) => Promise<unknown>;
  list: (args: { page?: number; page_size?: number; type?: string }) => Promise<unknown>;
  delete: (args: { memory_id: string }) => Promise<unknown>;
  getAutoMemory: () => Promise<unknown>;
  setAutoMemory: (args: { value: boolean }) => Promise<unknown>;
  findByTurn: (args: { turn_id: string }) => Promise<unknown>;
  getProfile: () => Promise<unknown>;
  getSummary: (args: { session_id: string }) => Promise<unknown>;
};
```

Extend `ElectronAPI` interface:

```typescript
interface ElectronAPI {
  // ... existing fields ...
  memory: MemoryApi;
}
```

- [ ] **Step 4: Manual smoke test**

Start backend: `/home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py`
Start Electron dev: `npm run tauri dev` or `npm run dev` + Electron shell

In the renderer DevTools console:

```javascript
await window.electronAPI.memory.list({ page: 1, page_size: 5 });
// Expected: { items: [...], total: N } — NOT "UnknownIpcCommandError"

await window.electronAPI.memory.getAutoMemory();
// Expected: "true" (default)
```

If either fails with `UnknownIpcCommandError`, re-check `electron/commands.ts` mapping and `invoke.ts` path substitution.

- [ ] **Step 5: Commit**

```bash
git add electron/commands.ts electron/invoke.ts electron/preload.ts
git commit -m "feat(memory): wire IPC commands for memory CRUD + prefs + traceability (gap D)"
```

---

## Task 2: auto_memory Flag (Gap B)

**Files:**
- Create: `backend/memory/lifecycle.py` (placeholder — HookRegistry used in Task 6)
- Modify: `backend/application/services/chat_service.py:391-456` (gate via lifecycle)
- Modify: `src/pages/Settings.tsx` (UI C — add Memory section)
- Create: `src/widgets/settings/Toggle.tsx` (if not exists)
- Test: `backend/tests/memory/test_lifecycle.py` (create with first test)

**Interfaces:**
- Consumes: `PreferencesRepository.get(key)` returning string or None
- Produces: `MemoryLifecycleManager.is_auto_memory_enabled() -> bool` (cached 30s, default True)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/memory/test_lifecycle.py`:

```python
import pytest
from backend.memory.lifecycle import MemoryLifecycleManager

@pytest.mark.asyncio
async def test_is_auto_memory_enabled_default_true_when_pref_missing():
    """When preferences table has no auto_memory key, default to True"""
    class FakePrefs:
        async def get(self, key: str):
            return None
    mgr = MemoryLifecycleManager(memory_manager=None, hooks=None, preferences_repo=FakePrefs())
    assert await mgr.is_auto_memory_enabled() is True

@pytest.mark.asyncio
async def test_is_auto_memory_enabled_respects_pref_false():
    class FakePrefs:
        async def get(self, key: str):
            return "false"
    mgr = MemoryLifecycleManager(memory_manager=None, hooks=None, preferences_repo=FakePrefs())
    assert await mgr.is_auto_memory_enabled() is False

@pytest.mark.asyncio
async def test_is_auto_memory_enabled_caches_for_30s():
    """Reading the pref twice within 30s should hit cache"""
    call_count = 0
    class CountingPrefs:
        async def get(self, key: str):
            nonlocal call_count
            call_count += 1
            return "true"
    mgr = MemoryLifecycleManager(memory_manager=None, hooks=None, preferences_repo=CountingPrefs())
    await mgr.is_auto_memory_enabled()
    await mgr.is_auto_memory_enabled()
    await mgr.is_auto_memory_enabled()
    assert call_count == 1

@pytest.mark.asyncio
async def test_is_auto_memory_enabled_defaults_true_on_read_error():
    """When prefs.get raises, default to True (fail-open)"""
    class FailingPrefs:
        async def get(self, key: str):
            raise RuntimeError("db locked")
    mgr = MemoryLifecycleManager(memory_manager=None, hooks=None, preferences_repo=FailingPrefs())
    assert await mgr.is_auto_memory_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_lifecycle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.memory.lifecycle'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/memory/lifecycle.py`:

```python
"""MemoryLifecycleManager: wrap MemoryManager with hook-based observability.

Inspired by Hermes Agent's MemoryProvider lifecycle (initialize →
system_prompt_block → prefetch → sync_turn → on_session_end →
on_pre_compress). See docs/superpowers/specs/2026-08-04-auto-memory-wiring-design.md
"""
import asyncio
import time
from typing import Optional, Callable, Awaitable, List
import logging

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    """Wrap MemoryManager with hooks; never raise into ChatService."""
    
    _AUTO_MEMORY_TTL = 30.0
    
    def __init__(self, memory_manager, hooks, preferences_repo):
        self._memory = memory_manager
        self._hooks = hooks
        self._prefs = preferences_repo
        self._auto_memory_cache: Optional[bool] = None
        self._cache_timestamp: float = 0.0
        self._current_turn_id: Optional[str] = None
    
    def set_current_turn(self, turn_id: str) -> None:
        self._current_turn_id = turn_id
    
    async def is_auto_memory_enabled(self) -> bool:
        """Read auto_memory preference with 30s cache; default True."""
        now = time.monotonic()
        if self._auto_memory_cache is not None and (now - self._cache_timestamp) < self._AUTO_MEMORY_TTL:
            return self._auto_memory_cache
        try:
            val = await self._prefs.get("auto_memory")
            if val is None:
                enabled = True
            else:
                enabled = str(val).lower() == "true"
        except Exception as e:
            logger.warning(f"auto_memory pref read failed, defaulting True: {e}")
            enabled = True
        self._auto_memory_cache = enabled
        self._cache_timestamp = now
        return enabled
    
    def invalidate_auto_memory_cache(self) -> None:
        """Force next read to hit DB (debug/testing helper)."""
        self._auto_memory_cache = None
        self._cache_timestamp = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_lifecycle.py -v`
Expected: 4 passed

- [ ] **Step 5: Gate ChatService's extraction via lifecycle**

Open `backend/application/services/chat_service.py`. Around line 391-395 (the call to `_extract_and_store_memory`), refactor:

Current code (lines 391-410 approx):
```python
        await self._extract_and_store_memory(session_id, messages)
        await self.memory.compress(session_id)
```

Replace with:
```python
        # Gate via auto_memory flag (caches 30s)
        if hasattr(self.memory, 'is_auto_memory_enabled'):
            if not await self.memory.is_auto_memory_enabled():
                logger.debug("auto_memory disabled, skipping extraction")
            else:
                await self._extract_and_store_memory(session_id, messages)
                await self.memory.compress(session_id)
        else:
            # Legacy path: MemoryManager doesn't have lifecycle wrapper yet
            await self._extract_and_store_memory(session_id, messages)
            await self.memory.compress(session_id)
```

This is a no-op when `memory` is the raw `MemoryManager` (preserves backward compat for tests not yet wired) and gates when it's a `MemoryLifecycleManager`.

- [ ] **Step 6: Add Settings page UI C**

Open `src/pages/Settings.tsx`. Find the section that renders preferences toggles (likely a `<form>` or list). Add a new section:

```tsx
import { Brain } from 'lucide-react';

// Inside the Settings component:
const [autoMemory, setAutoMemory] = useState(true);
const [memoryRetrieval, setMemoryRetrieval] = useState(true);

useEffect(() => {
  (async () => {
    const v = await window.electronAPI.memory.getAutoMemory();
    setAutoMemory(String(v).toLowerCase() === 'true');
  })();
}, []);

const handleAutoMemoryChange = async (val: boolean) => {
  setAutoMemory(val);
  await window.electronAPI.memory.setAutoMemory({ value: val });
};

// In JSX, add:
<section className="settings-section">
  <h3 className="flex items-center gap-2">
    <Brain className="w-5 h-5" /> 记忆 (Memory)
  </h3>
  <Toggle
    label="自动记忆沉淀"
    description="每轮对话后自动提取并保存有价值的点"
    checked={autoMemory}
    onChange={handleAutoMemoryChange}
  />
  <Toggle
    label="记忆检索注入"
    description="对话时自动注入相关记忆到上下文"
    checked={memoryRetrieval}
    onChange={setMemoryRetrieval}
  />
  <Button onClick={() => navigate('/memory')}>
    查看记忆管理 →
  </Button>
</section>
```

`Toggle` and `Button` should already exist in `src/widgets/`. If `Toggle` doesn't exist, create `src/widgets/settings/Toggle.tsx`:

```tsx
export function Toggle({ label, description, checked, onChange }: {
  label: string; description: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 py-2 cursor-pointer">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full ${checked ? 'bg-blue-500' : 'bg-gray-300'}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </button>
      <div>
        <div className="font-medium">{label}</div>
        <div className="text-sm text-gray-500">{description}</div>
      </div>
    </label>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add backend/memory/lifecycle.py backend/tests/memory/test_lifecycle.py backend/application/services/chat_service.py src/pages/Settings.tsx src/widgets/settings/Toggle.tsx
git commit -m "feat(memory): auto_memory preference gate + Settings UI toggle (gap B)"
```

---

## Task 3: LLM Tool Registration (Gap C)

**Files:**
- Modify: `backend/main.py:128` (pass `tools` to `ChatService`)
- Modify: `backend/application/services/chat_service.py` (accept + forward `tools` param)
- Modify: `backend/agents/profiles.py` (add `memory_search` / `memory_save` to `primary` and `researcher` tool lists)
- Test: `backend/tests/tools/test_memory_tool_registration.py`

**Interfaces:**
- Consumes: existing `MemorySearchTool` (`backend/tools/memory_tool.py:29-90`) and `MemorySaveTool` (`backend/tools/memory_tool.py:96-150+`)
- Produces: `ToolRegistry` instance in `app.state.tools`, passed to `ChatService`

- [ ] **Step 1: Find existing ToolRegistry**

Run: `grep -rn "class ToolRegistry" backend/`
If found, use it. If not, check for `ToolExecutor` / `tool_set` / similar. Document the actual class name in step 3.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/tools/test_memory_tool_registration.py`:

```python
import pytest
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

def test_memory_search_tool_schema_present():
    """Tool must declare itself with schema name 'memory_search'"""
    tool = MemorySearchTool(memory_port=None)  # mock port
    schemas = tool.get_schemas()
    assert any(s.get("name") == "memory_search" for s in schemas), schemas

def test_memory_save_tool_schema_present():
    tool = MemorySaveTool(memory_port=None)
    schemas = tool.get_schemas()
    assert any(s.get("name") == "memory_save" for s in schemas), schemas

def test_chat_service_accepts_tools():
    """ChatService __init__ must accept `tools` kwarg"""
    from backend.application.services.chat_service import ChatService
    import inspect
    sig = inspect.signature(ChatService.__init__)
    assert 'tools' in sig.parameters
```

- [ ] **Step 3: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/tools/test_memory_tool_registration.py -v`
Expected: FAIL (either `ModuleNotFoundError` for `test_memory_tool_registration.py`, or the `test_chat_service_accepts_tools` fails because `tools` param doesn't exist)

- [ ] **Step 4: Inspect existing tool implementations**

Open `backend/tools/memory_tool.py`. Confirm both `MemorySearchTool` and `MemorySaveTool` expose a method returning their schemas (likely `get_schemas()` or `to_openai_tools()` or similar). Note the exact method name.

If the method is named differently than `get_schemas`, adjust the test in step 2 accordingly. (Common names: `get_tool_definitions`, `to_schema`, `definitions`.)

- [ ] **Step 5: Make `ChatService.__init__` accept `tools`**

Open `backend/application/services/chat_service.py`. Find `ChatService.__init__`. Add `tools` parameter:

```python
def __init__(
    self,
    llm,
    memory,
    *,
    tools=None,           # NEW
    skill_port=None,
    diagram_tool=None,
    ...
):
    # ... existing params ...
    self._tools = tools  # NEW: store ToolRegistry (or None)
```

If the class doesn't use keyword-only args (no `*,` before `tools`), put it after existing required args and add a `# noqa` if needed.

- [ ] **Step 6: Forward tools when building LLM request**

Find the place in `ChatService.run_turn()` where the LLM request is constructed (search for `await self._llm.chat(` or `tools=`). Add tool forwarding:

```python
# Before LLM call:
available_tools = []
if self._tools is not None:
    available_tools = self._tools.get_schemas_for_agent(active_agent_profile)

response = await self._llm.chat(
    messages=messages,
    system=system_prompt,
    tools=available_tools,  # NEW
    ...
)
```

If `get_schemas_for_agent` doesn't exist on the ToolRegistry, find the actual method (likely `get_schemas()` returning all schemas, possibly filtered by agent profile).

- [ ] **Step 7: Update agent profiles**

Open `backend/agents/profiles.py`. Find `AGENT_PROFILES` dict. For `"primary"` and `"researcher"`, add `memory_search` and `memory_save` to their `tools` list:

```python
AGENT_PROFILES = {
    "primary": {
        # ... existing ...
        "tools": ["memory_search", "memory_save", ...existing_tools],
    },
    "researcher": {
        # ... existing ...
        "tools": ["memory_search", "memory_save", ...existing_tools],
    },
    # "coder" and "memory_manager" already had memory tools declared but unused
}
```

- [ ] **Step 8: Wire ToolRegistry into main.py lifespan**

Open `backend/main.py`. Find the section where `ChatService(...)` is constructed (around line 109-117). Replace `skills=None` with proper tool registration:

```python
# Import at top of main.py
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

# In lifespan startup, after memory_adapter is created:
memory_search_tool = MemorySearchTool(memory_port=memory_adapter)
memory_save_tool = MemorySaveTool(memory_port=memory_adapter)
# Register into whatever tool container exists in the codebase
# (look for existing pattern; e.g. tool_registry.register(...))
tool_registry = app.state.tool_registry  # or construct fresh
tool_registry.register(memory_search_tool)
tool_registry.register(memory_save_tool)

chat_service = ChatService(
    llm=llm_adapter,
    memory=lifecycle_manager,  # OR memory_adapter if lifecycle not yet wired
    tools=tool_registry,
    # ... other args ...
)
```

If the existing pattern uses a different mechanism (e.g. `app.state.skills` list, or explicit tool list passed to a `SkillPort`), follow that pattern instead.

- [ ] **Step 9: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/tools/test_memory_tool_registration.py -v`
Expected: 3 passed

- [ ] **Step 10: Manual smoke: LLM can call memory_save**

Start backend. Open a session in Electron. Send: "请记住我最喜欢的颜色是蓝色。"

Then send: "我最喜欢的颜色是什么？"

Expected: LLM responds with "蓝色" by calling `memory_search` tool. Check backend logs for `[MemorySearchTool.execute]` trace.

If LLM doesn't call the tool, check `agents/profiles.py` to confirm the active agent has memory tools in its list.

- [ ] **Step 11: Commit**

```bash
git add backend/main.py backend/application/services/chat_service.py backend/agents/profiles.py backend/tests/tools/test_memory_tool_registration.py
git commit -m "feat(memory): register memory_search/memory_save as LLM tools (gap C)"
```

---

## Task 4: Evolution Scheduler + Lifecycle Hooks (Gap A)

**Files:**
- Create: `backend/memory/hooks.py` (HookRegistry)
- Modify: `backend/memory/lifecycle.py` (add `on_turn_complete`, `on_session_end`, `on_pre_compress`)
- Modify: `backend/main.py` (lifespan: wire EvolutionScheduler + watchdog)
- Modify: `backend/scheduler/evolution.py` (emit `evolution_completed` hook)
- Modify: `backend/data/database.py` (idempotent schema migration for traceability columns)
- Modify: `backend/adapters/out/memory/adapter.py` (store with `source_turn_id` / `memory_category`)
- Modify: `backend/memory/extractor.py` (pass `source_turn_id` / categorize)
- Modify: `backend/memory/manager.py` (thread traceability through `remember()`)
- Modify: `backend/memory/episodic.py` (INSERT with new columns)
- Test: `backend/tests/memory/test_hooks.py`, extend `backend/tests/memory/test_lifecycle.py`

**Interfaces:**
- Consumes: existing `MemoryManager.remember()`, `MemoryManager.consolidate()`, `MemoryManager.snapshot()`
- Produces: `HookRegistry.on/off/emit`, `MemoryLifecycleManager.on_turn_complete/on_session_end/on_pre_compress`

- [ ] **Step 1: Write HookRegistry failing test**

Create `backend/tests/memory/test_hooks.py`:

```python
import pytest
from backend.memory.hooks import HookRegistry

@pytest.mark.asyncio
async def test_emit_calls_all_listeners():
    reg = HookRegistry()
    calls = []
    reg.on("test", lambda x: calls.append(("sync", x)))
    async def async_listener(x): calls.append(("async", x))
    reg.on("test", async_listener)
    await reg.emit("test", "payload")
    assert ("sync", "payload") in calls
    assert ("async", "payload") in calls

@pytest.mark.asyncio
async def test_listener_exception_does_not_block_others():
    reg = HookRegistry()
    calls = []
    def bad(x): raise RuntimeError("boom")
    reg.on("test", bad)
    reg.on("test", lambda x: calls.append(x))
    await reg.emit("test", "p")  # must NOT raise
    assert calls == ["p"]

@pytest.mark.asyncio
async def test_off_removes_listener():
    reg = HookRegistry()
    calls = []
    cb = lambda x: calls.append(x)
    reg.on("test", cb)
    reg.off("test", cb)
    await reg.emit("test", "p")
    assert calls == []

@pytest.mark.asyncio
async def test_emit_with_no_listeners_is_noop():
    reg = HookRegistry()
    await reg.emit("nobody", "p")  # must NOT raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_hooks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.memory.hooks'`

- [ ] **Step 3: Implement HookRegistry**

Create `backend/memory/hooks.py`:

```python
"""Process-local pub/sub for memory lifecycle events."""
import asyncio
import logging
from typing import Callable, Dict, List, Union

logger = logging.getLogger(__name__)

AsyncOrSyncListener = Callable[[object], Union[None, "asyncio.Future[None]"]]


class HookRegistry:
    def __init__(self) -> None:
        self._listeners: Dict[str, List[AsyncOrSyncListener]] = {}
    
    def on(self, event: str, callback: AsyncOrSyncListener) -> None:
        self._listeners.setdefault(event, []).append(callback)
    
    def off(self, event: str, callback: AsyncOrSyncListener) -> None:
        if event in self._listeners:
            self._listeners[event] = [cb for cb in self._listeners[event] if cb is not callback]
    
    async def emit(self, event: str, payload: object) -> None:
        listeners = list(self._listeners.get(event, []))
        for cb in listeners:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.exception(f"hook listener for {event!r} raised", exc_info=e)
    
    def emit_sync(self, event: str, payload: object) -> None:
        """Synchronous emit for tests; schedules async on event loop."""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self.emit(event, payload))
        else:
            loop.run_until_complete(self.emit(event, payload))
```

- [ ] **Step 4: Run HookRegistry test**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_hooks.py -v`
Expected: 4 passed

- [ ] **Step 5: Write failing tests for lifecycle hooks**

Extend `backend/tests/memory/test_lifecycle.py` with:

```python
@pytest.mark.asyncio
async def test_on_turn_complete_calls_remember_and_emits_hook():
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager
    
    class FakeMemory:
        def __init__(self):
            self.remember_calls = []
        async def remember(self, **kwargs):
            self.remember_calls.append(kwargs)
            # Return 2 mock memories
            class Mem:
                def __init__(self, id, content, category):
                    self.id = id; self.content = content; self.category = category; self.type = "episodic"
            return [Mem("m1", "fact 1", "user_pref"), Mem("m2", "fact 2", "project_fact")]
    
    class FakePrefs:
        async def get(self, key): return "true"
    
    hooks = HookRegistry()
    events = []
    hooks.on("memory_written", lambda e: events.append(e))
    
    mgr = MemoryLifecycleManager(memory_manager=FakeMemory(), hooks=hooks, preferences_repo=FakePrefs())
    mgr.set_current_turn("turn-1")
    await mgr.on_turn_complete("session-1", [{"role": "user", "content": "hi"}])
    
    assert len(events) == 2
    assert events[0].content == "fact 1"
    assert events[0].turn_id == "turn-1"

@pytest.mark.asyncio
async def test_on_turn_complete_skips_when_auto_memory_false():
    from backend.memory.lifecycle import MemoryLifecycleManager
    from backend.memory.hooks import HookRegistry
    
    class FakeMemory:
        async def remember(self, **kwargs): raise AssertionError("should not be called")
    
    class FakePrefs:
        async def get(self, key): return "false"
    
    hooks = HookRegistry()
    mgr = MemoryLifecycleManager(memory_manager=FakeMemory(), hooks=hooks, preferences_repo=FakePrefs())
    await mgr.on_turn_complete("session-1", [])  # must not raise

@pytest.mark.asyncio
async def test_on_session_end_calls_consolidate():
    from backend.memory.lifecycle import MemoryLifecycleManager
    from backend.memory.hooks import HookRegistry
    
    consolidate_calls = []
    class FakeMemory:
        async def consolidate(self, session_id):
            consolidate_calls.append(session_id)
    
    events = []
    hooks = HookRegistry()
    hooks.on("session_ended", lambda e: events.append(e))
    
    mgr = MemoryLifecycleManager(memory_manager=FakeMemory(), hooks=hooks, preferences_repo=None)
    await mgr.on_session_end("session-99")
    assert consolidate_calls == ["session-99"]
    assert len(events) == 1

@pytest.mark.asyncio
async def test_lifecycle_never_raises_into_caller():
    """Even if memory throws, lifecycle must swallow."""
    from backend.memory.lifecycle import MemoryLifecycleManager
    from backend.memory.hooks import HookRegistry
    
    class BrokenMemory:
        async def remember(self, **kw): raise RuntimeError("db broken")
    
    class FakePrefs:
        async def get(self, key): return "true"
    
    mgr = MemoryLifecycleManager(memory_manager=BrokenMemory(), hooks=HookRegistry(), preferences_repo=FakePrefs())
    # Must not raise:
    await mgr.on_turn_complete("s", [])
```

- [ ] **Step 6: Run lifecycle tests to verify they fail**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_lifecycle.py -v`
Expected: 4 new tests FAIL (hook methods don't exist yet)

- [ ] **Step 7: Extend MemoryLifecycleManager with hook methods**

Modify `backend/memory/lifecycle.py`. Add at top:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class MemoryWriteEvent:
    memory_id: str
    content: str
    memory_type: str
    memory_category: str
    session_id: str
    turn_id: Optional[str]
    timestamp: datetime

@dataclass
class SessionEndEvent:
    session_id: str
    timestamp: datetime

@dataclass
class PreCompressEvent:
    session_id: str
    timestamp: datetime

def utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

Add three hook methods to `MemoryLifecycleManager` class:

```python
    async def on_turn_complete(self, session_id: str, messages: list) -> None:
        if not await self.is_auto_memory_enabled():
            return
        try:
            extracted = await self._memory.remember(
                session_id=session_id,
                messages=messages,
                source_turn_id=self._current_turn_id,
            )
            for mem in (extracted or []):
                await self._hooks.emit("memory_written", MemoryWriteEvent(
                    memory_id=mem.id,
                    content=mem.content,
                    memory_type=getattr(mem, "type", "episodic"),
                    memory_category=getattr(mem, "category", "project_fact"),
                    session_id=session_id,
                    turn_id=self._current_turn_id,
                    timestamp=utcnow(),
                ))
        except Exception as e:
            logger.exception("on_turn_complete failed", exc_info=e)
    
    async def on_session_end(self, session_id: str) -> None:
        try:
            await self._memory.consolidate(session_id)
            await self._hooks.emit("session_ended", SessionEndEvent(
                session_id=session_id, timestamp=utcnow(),
            ))
        except Exception as e:
            logger.exception("on_session_end failed", exc_info=e)
    
    async def on_pre_compress(self, session_id: str) -> None:
        try:
            await self._memory.snapshot(session_id)
            await self._hooks.emit("pre_compress", PreCompressEvent(
                session_id=session_id, timestamp=utcnow(),
            ))
        except Exception as e:
            logger.exception("on_pre_compress failed", exc_info=e)
```

- [ ] **Step 8: Run lifecycle tests to verify they pass**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/memory/test_lifecycle.py -v`
Expected: all 8 tests pass (4 original + 4 new)

- [ ] **Step 9: Idempotent DB schema migration**

Open `backend/data/database.py`. Find the section that runs CREATE TABLE statements (around line 109-129 for `memories_episodic`). Add a migration function:

```python
def _migrate_memory_traceability(db: sqlite3.Connection) -> None:
    """Add source_turn_id / source_message_id / memory_category columns + indexes.
    Idempotent: safe to call on every startup."""
    cur = db.execute("PRAGMA table_info(memories_episodic)")
    existing_cols = {row[1] for row in cur.fetchall()}
    
    new_cols = {
        "source_turn_id": "TEXT",
        "source_message_id": "TEXT",
        "memory_category": "TEXT",
    }
    for col, typedef in new_cols.items():
        if col not in existing_cols:
            db.execute(f"ALTER TABLE memories_episodic ADD COLUMN {col} {typedef}")
            logger.info(f"migration: added memories_episodic.{col}")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_mem_episodic_session_turn "
               "ON memories_episodic(session_id, source_turn_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mem_episodic_category "
               "ON memories_episodic(memory_category)")
    db.commit()
```

Call `_migrate_memory_traceability(db)` in the `init_database` function (or wherever initial schema setup runs).

- [ ] **Step 10: Extend `EpisodicMemory.store()` for traceability columns**

Open `backend/memory/episodic.py`. Find the `store()` method's INSERT statement. Add columns `source_turn_id`, `source_message_id`, `memory_category`. Update method signature:

```python
async def store(
    self,
    content: str,
    *,
    importance: int = 5,
    session_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source_turn_id: Optional[str] = None,
    source_message_id: Optional[str] = None,
    memory_category: Optional[str] = None,
) -> MemoryItem:
    # ... existing logic, but include new columns in INSERT ...
```

- [ ] **Step 11: Extend `MemoryAdapter.store()` to accept traceability params**

Open `backend/adapters/out/memory/adapter.py`. Find the `store()` method. Add `source_turn_id`, `source_message_id`, `memory_category` params and forward to `EpisodicMemory.store()`.

- [ ] **Step 12: Extend `MemoryManager.remember()` to thread traceability**

Open `backend/memory/manager.py`. Find `remember()` method. Pass `source_turn_id` through to the underlying `MemoryAdapter.store()` call.

- [ ] **Step 13: Update `MemoryExtractor` to categorize**

Open `backend/memory/extractor.py`. In the extraction prompt or post-processing, assign `memory_category` ∈ {`user_pref`, `project_fact`, `task_summary`, `cross_session_pattern`}. Default to `project_fact` if uncertain.

Simple heuristic: if extracted fact contains words like "喜欢 / 偏好 / 讨厌 / 不要 / 记得 / 以后" → `user_pref`. Else → `project_fact`.

- [ ] **Step 14: Update evolution tasks to emit hooks**

Open `backend/scheduler/evolution.py`. Each task class (`DailySummaryTask`, `PreferenceLearningTask`, etc.) has a `run_once()` method. Modify the base class or each task to emit `evolution_completed` after successful run:

```python
# At end of each run_once():
await self._hooks.emit("evolution_completed", {
    "task_name": self.__class__.__name__,
    "items_processed": N,
    "duration_ms": elapsed_ms,
    "timestamp": utcnow().isoformat(),
})
```

Add `hooks` param to task constructors. Update `create_evolution_tasks()` to accept and pass `hooks`.

- [ ] **Step 15: Wire EvolutionScheduler into lifespan**

Open `backend/main.py`. In `lifespan` startup (after memory setup):

```python
hooks = HookRegistry()
lifecycle = MemoryLifecycleManager(
    memory_manager=memory_manager,
    hooks=hooks,
    preferences_repo=preferences_repo,
)
app.state.hooks = hooks
app.state.lifecycle = lifecycle

evolution_scheduler = EvolutionScheduler()
for task in create_evolution_tasks(memory_manager=memory_manager, hooks=hooks):
    evolution_scheduler.register(task)
await evolution_scheduler.start()
app.state.evolution_scheduler = evolution_scheduler

# Session-end watchdog
async def _session_watchdog():
    while True:
        try:
            await asyncio.sleep(60)
            # Scan sessions table, find ones not updated in 30+ min
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            stale = db_query("SELECT id FROM sessions WHERE updated_at < ?", (cutoff,))
            for sid in stale:
                await lifecycle.on_session_end(sid)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("session_watchdog error")

watchdog_task = asyncio.create_task(_session_watchdog())
app.state.session_watchdog = watchdog_task
```

In shutdown:

```python
watchdog_task.cancel()
await evolution_scheduler.stop()
```

- [ ] **Step 16: Smoke test: evolution tasks actually run**

Start backend. Wait 3-5 minutes. Check logs for evolution task ticks. Or set a short cron temporarily (override `0 3 * * *` → `* * * * *` for testing).

Verify with: `curl http://127.0.0.1:8765/api/v1/evolution/logs` returns entries.

- [ ] **Step 17: Commit**

```bash
git add backend/memory/hooks.py backend/memory/lifecycle.py backend/memory/extractor.py backend/memory/manager.py backend/memory/episodic.py backend/adapters/out/memory/adapter.py backend/scheduler/evolution.py backend/data/database.py backend/main.py backend/tests/memory/
git commit -m "feat(memory): lifecycle hooks + EvolutionScheduler auto-run + traceability schema (gap A)"
```

---

## Task 5: Dedicated Endpoints + Traceability UI (Gap E)

**Files:**
- Modify: `backend/ports/memory.py` (add `find_by_turn`, `find_by_category`, `find_by_category_and_session` to `MemoryPort`)
- Modify: `backend/adapters/out/memory/adapter.py` (implement new methods)
- Modify: `backend/memory/episodic.py` (SQLite queries)
- Modify: `backend/api/legacy_routes.py` (3 new endpoints: by-turn, profile, summary)
- Modify: `src/widgets/Sidebar.tsx` (add Memory entry)
- Create: `src/pages/Memory.tsx` (3-tab page)
- Create: `src/widgets/memory/MemoryCard.tsx`
- Create: `src/widgets/memory/MemoryTabs.tsx`
- Modify: `src/pages/Chat.tsx` (support `highlight_turn` query param)
- Modify: `src/router.tsx` (add `/memory` route)
- Create: `src/widgets/memory/__tests__/MemoryCard.spec.tsx`
- Test: `backend/tests/api/test_memory_endpoints.py`

**Interfaces:**
- Consumes: existing `/api/v1/memory/list` pagination
- Produces: 3 new endpoints + frontend Memory page with tabs

- [ ] **Step 1: Write failing tests for new MemoryPort methods**

Create `backend/tests/api/test_memory_endpoints.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_find_by_turn_returns_empty_when_no_match():
    from backend.adapters.out.memory.adapter import MemoryAdapter
    # Adapter with in-memory test DB
    adapter = MemoryAdapter(test_db_path=":memory:")
    result = await adapter.find_by_turn("nonexistent-turn")
    assert result == []

@pytest.mark.asyncio
async def test_find_by_category_filters_correctly():
    adapter = MemoryAdapter(test_db_path=":memory:")
    await adapter.store("user likes cats", importance=8, memory_category="user_pref", source_turn_id="t1")
    await adapter.store("project uses React", importance=5, memory_category="project_fact", source_turn_id="t2")
    prefs = await adapter.find_by_category("user_pref")
    assert len(prefs) == 1
    assert "cats" in prefs[0].content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_memory_endpoints.py -v`
Expected: FAIL (`find_by_turn` / `find_by_category` don't exist)

- [ ] **Step 3: Add methods to MemoryPort protocol**

Open `backend/ports/memory.py`. Add to the `MemoryPort` Protocol:

```python
    async def find_by_turn(self, turn_id: str) -> list[MemoryItem]:
        """Return all memories with source_turn_id == turn_id."""
        ...
    
    async def find_by_category(self, category: str, *, limit: int = 50) -> list[MemoryItem]:
        """Return memories filtered by memory_category, newest first."""
        ...
    
    async def find_by_category_and_session(self, category: str, session_id: str) -> list[MemoryItem]:
        """Return memories filtered by category AND session_id."""
        ...
```

- [ ] **Step 4: Implement in MemoryAdapter and EpisodicMemory**

Open `backend/adapters/out/memory/adapter.py`. Add the three methods:

```python
    async def find_by_turn(self, turn_id: str) -> list[MemoryItem]:
        return await self._episodic.find_by_turn(turn_id)
    
    async def find_by_category(self, category: str, *, limit: int = 50) -> list[MemoryItem]:
        return await self._episodic.find_by_category(category, limit=limit)
    
    async def find_by_category_and_session(self, category: str, session_id: str) -> list[MemoryItem]:
        return await self._episodic.find_by_category_and_session(category, session_id)
```

Add corresponding methods in `backend/memory/episodic.py` (SQLite queries against the new columns):

```python
async def find_by_turn(self, turn_id: str) -> list[MemoryItem]:
    cur = self._db.execute(
        "SELECT * FROM memories_episodic WHERE source_turn_id = ? AND is_valid = 1 ORDER BY created_at DESC",
        (turn_id,),
    )
    return [self._row_to_item(row) for row in cur.fetchall()]

async def find_by_category(self, category: str, *, limit: int = 50) -> list[MemoryItem]:
    cur = self._db.execute(
        "SELECT * FROM memories_episodic WHERE memory_category = ? AND is_valid = 1 ORDER BY created_at DESC LIMIT ?",
        (category, limit),
    )
    return [self._row_to_item(row) for row in cur.fetchall()]

async def find_by_category_and_session(self, category: str, session_id: str) -> list[MemoryItem]:
    cur = self._db.execute(
        "SELECT * FROM memories_episodic WHERE memory_category = ? AND session_id = ? AND is_valid = 1 ORDER BY created_at DESC",
        (category, session_id),
    )
    return [self._row_to_item(row) for row in cur.fetchall()]
```

- [ ] **Step 5: Add 3 new endpoints to legacy_routes.py**

Open `backend/api/legacy_routes.py`. Add after existing `/memory/list` endpoint:

```python
@router.get("/memory/by-turn/{turn_id}")
async def get_memories_by_turn(turn_id: str, request: Request):
    memory_port = request.app.state.memory_port
    memories = await memory_port.find_by_turn(turn_id)
    return {"memories": [m.to_dict() for m in memories]}

@router.get("/memory/profile")
async def get_user_profile(request: Request):
    memory_port = request.app.state.memory_port
    prefs = await memory_port.find_by_category("user_pref", limit=50)
    decisions = await memory_port.find_by_category("decision", limit=20)
    facts = await memory_port.find_by_category("project_fact", limit=50)
    return {
        "preferences": [m.to_dict() for m in prefs if m.importance >= 7],
        "decisions": [m.to_dict() for m in decisions],
        "facts": [m.to_dict() for m in facts],
        "total_count": len(prefs) + len(decisions) + len(facts),
    }

@router.get("/memory/summary/{session_id}")
async def get_session_summary(session_id: str, request: Request):
    memory_port = request.app.state.memory_port
    summaries = await memory_port.find_by_category_and_session("task_summary", session_id)
    return {"summaries": [m.to_dict() for m in summaries], "session_id": session_id}
```

- [ ] **Step 6: Run backend tests**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_memory_endpoints.py -v`
Expected: 2 passed

Manual smoke:
```bash
curl http://127.0.0.1:8765/api/v1/memory/profile
# Expected: {"preferences": [], "decisions": [], "facts": [], "total_count": 0}
```

- [ ] **Step 7: Add Sidebar Memory entry**

Open `src/widgets/Sidebar.tsx`. Find the navigation items list. Add:

```tsx
import { Brain } from 'lucide-react';

// In nav items array:
{ icon: Brain, label: 'Memory', path: '/memory' },
```

If `lucide-react` is not already a dep, install: `npm install lucide-react`. Or use `🧠` emoji fallback.

- [ ] **Step 8: Create MemoryCard component**

Create `src/widgets/memory/MemoryCard.tsx`:

```tsx
import { Trash2, MapPin } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface MemoryItem {
  id: string;
  content: string;
  importance: number;
  memory_type: string;
  memory_category: string;
  session_id?: string;
  source_turn_id?: string;
  created_at: string;
}

export function MemoryCard({ memory, onDelete }: {
  memory: MemoryItem;
  onDelete: (id: string) => void;
}) {
  const navigate = useNavigate();
  
  const handleTraceabilityClick = () => {
    if (memory.session_id && memory.source_turn_id) {
      navigate(`/chat?session=${memory.session_id}&highlight_turn=${memory.source_turn_id}`);
    }
  };
  
  const categoryLabel: Record<string, string> = {
    user_pref: '用户偏好',
    project_fact: '项目事实',
    task_summary: '任务总结',
    decision: '决策',
    cross_session_pattern: '跨会话模式',
  };
  
  return (
    <div className="border rounded-lg p-4 mb-2 bg-white dark:bg-gray-800">
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs text-gray-500">
          🧠 {categoryLabel[memory.memory_category] ?? memory.memory_category} · {new Date(memory.created_at).toLocaleString('zh-CN')}
        </span>
        <button onClick={() => onDelete(memory.id)} className="text-red-500 hover:text-red-700">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <p className="text-sm mb-2">{memory.content}</p>
      <div className="flex justify-between items-center text-xs text-gray-500">
        <span>importance: {memory.importance}</span>
        {memory.session_id && memory.source_turn_id && (
          <button onClick={handleTraceabilityClick} className="flex items-center gap-1 hover:text-blue-500">
            <MapPin className="w-3 h-3" />
            Session #{memory.session_id.slice(0, 8)} · Turn #{memory.source_turn_id.slice(0, 8)}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 9: Create MemoryTabs component**

Create `src/widgets/memory/MemoryTabs.tsx`:

```tsx
import { useState } from 'react';

export type MemoryTab = 'all' | 'profile' | 'summary';

export function MemoryTabs({ active, onChange }: {
  active: MemoryTab;
  onChange: (tab: MemoryTab) => void;
}) {
  const tabs: { key: MemoryTab; label: string }[] = [
    { key: 'all', label: '所有记忆' },
    { key: 'profile', label: '用户档案' },
    { key: 'summary', label: '会话摘要' },
  ];
  
  return (
    <div className="flex border-b mb-4">
      {tabs.map(tab => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`px-4 py-2 ${active === tab.key ? 'border-b-2 border-blue-500 font-medium' : 'text-gray-500'}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 10: Create Memory page**

Create `src/pages/Memory.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { MemoryCard } from '@/widgets/memory/MemoryCard';
import { MemoryTabs, MemoryTab } from '@/widgets/memory/MemoryTabs';
import { Search } from 'lucide-react';

export function MemoryPage() {
  const [tab, setTab] = useState<MemoryTab>('all');
  const [memories, setMemories] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  
  useEffect(() => {
    loadMemories();
  }, [tab, search, typeFilter]);
  
  async function loadMemories() {
    if (tab === 'profile') {
      const data: any = await window.electronAPI.memory.getProfile();
      setMemories([
        ...(data.preferences || []),
        ...(data.decisions || []),
        ...(data.facts || []),
      ]);
    } else {
      const args: any = { page: 1, page_size: 50 };
      if (search) args.query = search;
      if (typeFilter) args.type = typeFilter;
      const data: any = await window.electronAPI.memory.list(args);
      setMemories(data.items || []);
    }
  }
  
  async function handleDelete(id: string) {
    await window.electronAPI.memory.delete({ memory_id: id });
    setMemories(prev => prev.filter(m => m.id !== id));
  }
  
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">🧠 记忆管理</h1>
      
      <div className="flex gap-2 mb-4">
        <div className="flex-1 flex items-center gap-2 border rounded px-3 py-2">
          <Search className="w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="搜索记忆..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="flex-1 outline-none"
          />
        </div>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="border rounded px-3">
          <option value="">全部类型</option>
          <option value="user_pref">用户偏好</option>
          <option value="project_fact">项目事实</option>
          <option value="task_summary">任务总结</option>
        </select>
      </div>
      
      <MemoryTabs active={tab} onChange={setTab} />
      
      {memories.length === 0 ? (
        <p className="text-gray-500 text-center py-8">暂无记忆</p>
      ) : (
        memories.map(m => <MemoryCard key={m.id} memory={m} onDelete={handleDelete} />)
      )}
    </div>
  );
}
```

Add to router config (`src/router.tsx` or wherever routes are defined):

```tsx
import { MemoryPage } from '@/pages/Memory';
// Add route: { path: '/memory', element: <MemoryPage /> }
```

- [ ] **Step 11: Add Chat page highlight_turn support**

Open `src/pages/Chat.tsx`. Find where messages are loaded and rendered. After messages load, check URL params:

```tsx
import { useSearchParams } from 'react-router-dom';

const [searchParams] = useSearchParams();
const highlightTurn = searchParams.get('highlight_turn');

useEffect(() => {
  if (!highlightTurn || !messages.length) return;
  const el = document.querySelector(`[data-turn-id="${highlightTurn}"]`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-blue-500');
    setTimeout(() => el.classList.remove('ring-2', 'ring-blue-500'), 2000);
  }
}, [highlightTurn, messages]);
```

Add `data-turn-id` attribute to message containers in the render.

- [ ] **Step 12: Write MemoryCard test**

Create `src/widgets/memory/__tests__/MemoryCard.spec.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryCard } from '../MemoryCard';
import { vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const mockMemory = {
  id: 'm1',
  content: '用户偏好 KISS 风格',
  importance: 8,
  memory_type: 'episodic',
  memory_category: 'user_pref',
  session_id: 'abc-123',
  source_turn_id: 'turn-42',
  created_at: '2026-08-04T17:30:00Z',
};

describe('MemoryCard', () => {
  it('renders content and category label', () => {
    render(<MemoryCard memory={mockMemory} onDelete={() => {}} />, { wrapper: MemoryRouter });
    expect(screen.getByText('用户偏好 KISS 风格')).toBeInTheDocument();
    expect(screen.getByText(/用户偏好/)).toBeInTheDocument();
  });
  
  it('shows traceability button when session_id and turn_id present', () => {
    render(<MemoryCard memory={mockMemory} onDelete={() => {}} />, { wrapper: MemoryRouter });
    expect(screen.getByText(/Session/)).toBeInTheDocument();
  });
  
  it('calls onDelete when trash clicked', () => {
    const onDelete = vi.fn();
    render(<MemoryCard memory={mockMemory} onDelete={onDelete} />, { wrapper: MemoryRouter });
    fireEvent.click(screen.getByRole('button', { name: '' }));  // trash icon
    expect(onDelete).toHaveBeenCalledWith('m1');
  });
  
  it('hides traceability when source_turn_id missing', () => {
    const m = { ...mockMemory, source_turn_id: undefined };
    render(<MemoryCard memory={m} onDelete={() => {}} />, { wrapper: MemoryRouter });
    expect(screen.queryByText(/Session/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 13: Run frontend tests**

Run: `npm test -- MemoryCard.spec`
Expected: 4 passed

- [ ] **Step 14: Commit**

```bash
git add backend/ports/memory.py backend/adapters/out/memory/adapter.py backend/memory/episodic.py backend/api/legacy_routes.py src/widgets/Sidebar.tsx src/pages/Memory.tsx src/widgets/memory/ src/pages/Chat.tsx src/router.tsx backend/tests/api/test_memory_endpoints.py src/widgets/memory/__tests__/
git commit -m "feat(memory): traceability endpoints + Sidebar/Memory page with click-to-trace (gap E)"
```

---

## Task 6: SSE Observability + Real-time UI Updates

**Files:**
- Modify: `backend/api/legacy_routes.py` (add `/memory/events` SSE endpoint)
- Modify: `electron/main.ts` (SSE relay)
- Modify: `electron/preload.ts` (expose `memory.subscribe`)
- Modify: `src/pages/Memory.tsx` (subscribe to SSE, toast on new memory)
- Test: `backend/tests/api/test_memory_sse.py`, `src/widgets/memory/__tests__/MemorySSE.spec.tsx`

**Interfaces:**
- Consumes: `HookRegistry.emit("memory_written", event)`
- Produces: SSE stream at `/api/v1/memory/events`, Electron-side relay, renderer-side toast + list prepend

- [ ] **Step 1: Write failing SSE test**

Create `backend/tests/api/test_memory_sse.py`:

```python
import pytest
import asyncio
from backend.memory.hooks import HookRegistry

@pytest.mark.asyncio
async def test_sse_endpoint_streams_memory_written_events():
    """Connect to /memory/events, emit hook, verify event received."""
    from fastapi.testclient import TestClient
    from backend.main import app
    
    with TestClient(app) as client:
        # Start SSE stream in background task
        async def consume():
            events = []
            with client.stream("GET", "/api/v1/memory/events") as r:
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        events.append(line[6:])
                        if len(events) >= 1:
                            break
            return events
        
        consume_task = asyncio.create_task(consume())
        await asyncio.sleep(0.5)  # let SSE connection establish
        
        # Emit hook
        hooks: HookRegistry = app.state.hooks
        from backend.memory.lifecycle import MemoryWriteEvent
        from datetime import datetime, timezone
        hooks.emit_sync("memory_written", MemoryWriteEvent(
            memory_id="test-1",
            content="test fact",
            memory_type="episodic",
            memory_category="user_pref",
            session_id="s1",
            turn_id="t1",
            timestamp=datetime.now(timezone.utc),
        ))
        
        events = await asyncio.wait_for(consume_task, timeout=5.0)
        assert len(events) >= 1
        assert "test fact" in events[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_memory_sse.py -v`
Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 3: Add SSE endpoint**

Open `backend/api/legacy_routes.py`. Add:

```python
from fastapi.responses import StreamingResponse

@router.get("/memory/events")
async def memory_events(request: Request):
    hooks: HookRegistry = request.app.state.hooks
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    
    async def on_memory_written(event):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("memory events queue full, dropping event")
    
    hooks.on("memory_written", on_memory_written)
    
    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload = json.dumps({
                        "memory_id": event.memory_id,
                        "content": event.content,
                        "memory_category": event.memory_category,
                        "session_id": event.session_id,
                        "turn_id": event.turn_id,
                        "timestamp": event.timestamp.isoformat(),
                    })
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hooks.off("memory_written", on_memory_written)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run SSE test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_memory_sse.py -v`
Expected: 1 passed

- [ ] **Step 5: Wire SSE relay in Electron main**

Open `electron/main.ts`. Find the existing `invokeBackend` function. Add a relay method that opens an SSE connection to backend and re-emits to renderer via IPC:

```typescript
import { EventSource } from 'eventsource';  // Node 18+ has global EventSource; if not, npm install eventsource

ipcMain.handle('sage:memory:subscribe', async (event) => {
  const sender = event.sender;
  const backendUrl = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';
  const es = new EventSource(`${backendUrl}/api/v1/memory/events`);
  
  es.onmessage = (msg) => {
    if (!sender.isDestroyed()) {
      sender.send('sage:memory:event', msg.data);
    }
  };
  
  es.onerror = (err) => {
    logger.error('SSE error', err);
    // Don't close — let EventSource auto-reconnect
  };
  
  // Store reference for cleanup
  memorySubscribers.set(sender.id, es);
  
  return { subscribed: true };
});

ipcMain.handle('sage:memory:unsubscribe', (event) => {
  const es = memorySubscribers.get(event.sender.id);
  if (es) {
    es.close();
    memorySubscribers.delete(event.sender.id);
  }
  return { unsubscribed: true };
});
```

If Node version doesn't have global EventSource, install: `npm install eventsource` in `electron/` directory.

- [ ] **Step 6: Expose SSE subscribe in preload**

Open `electron/preload.ts`. Add:

```typescript
  memory: {
    // ... existing methods ...
    subscribe: (callback: (event: unknown) => void) => {
      ipcRenderer.invoke('sage:memory:subscribe');
      const listener = (_e: unknown, data: unknown) => callback(data);
      ipcRenderer.on('sage:memory:event', listener);
      return () => {
        ipcRenderer.off('sage:memory:event', listener);
        ipcRenderer.invoke('sage:memory:unsubscribe');
      };
    },
  },
```

- [ ] **Step 7: Subscribe in Memory page**

Open `src/pages/Memory.tsx`. Add SSE subscription:

```tsx
import { toast } from '@/widgets/Toast';  // or use existing toast system

useEffect(() => {
  const unsubscribe = window.electronAPI.memory.subscribe((event: any) => {
    const data = JSON.parse(event);
    toast.success(`🧠 已记住: ${data.content}`);
    setMemories(prev => [data, ...prev]);  // prepend
  });
  return unsubscribe;
}, []);
```

- [ ] **Step 8: Add polling fallback**

In `src/pages/Memory.tsx`, wrap the subscribe with try/catch fallback:

```tsx
useEffect(() => {
  let unsubscribe: (() => void) | null = null;
  let pollInterval: number | null = null;
  
  try {
    unsubscribe = window.electronAPI.memory.subscribe((event: any) => {
      const data = JSON.parse(event);
      toast.success(`🧠 已记住: ${data.content}`);
      setMemories(prev => [data, ...prev]);
    });
  } catch (e) {
    console.warn('SSE failed, falling back to polling', e);
    pollInterval = window.setInterval(loadMemories, 30000);
  }
  
  return () => {
    unsubscribe?.();
    if (pollInterval) clearInterval(pollInterval);
  };
}, []);
```

- [ ] **Step 9: Write frontend SSE test**

Create `src/widgets/memory/__tests__/MemorySSE.spec.tsx`:

```tsx
import { render, act } from '@testing-library/react';
import { MemoryPage } from '@/pages/Memory';
import { vi } from 'vitest';

vi.mock('@/widgets/Toast', () => ({
  toast: { success: vi.fn() },
}));

describe('MemoryPage SSE integration', () => {
  it('subscribes to memory events on mount', () => {
    const subscribeMock = vi.fn(() => () => {});
    (window as any).electronAPI.memory.subscribe = subscribeMock;
    (window as any).electronAPI.memory.list = vi.fn(() => Promise.resolve({ items: [] }));
    
    render(<MemoryPage />);
    expect(subscribeMock).toHaveBeenCalled();
  });
});
```

- [ ] **Step 10: Run all tests**

Run backend: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -v`
Run frontend: `npm test`
Expected: all green

- [ ] **Step 11: E2E smoke test**

Manual:
1. Start backend + Electron dev
2. Open a session, send a message containing personal preference
3. Verify toast appears: "🧠 已记住: ..."
4. Navigate to /memory page
5. Verify new memory appears at top
6. Click traceability link → Chat page should scroll to source turn + highlight
7. Kill backend → restart → verify auto_memory preference is preserved (preferences table persisted)

- [ ] **Step 12: Commit**

```bash
git add backend/api/legacy_routes.py backend/memory/hooks.py electron/main.ts electron/preload.ts src/pages/Memory.tsx src/widgets/memory/ backend/tests/api/test_memory_sse.py src/widgets/memory/__tests__/MemorySSE.spec.tsx
git commit -m "feat(memory): SSE /memory/events + real-time UI updates with polling fallback"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| MemoryLifecycleManager | T2 (skeleton), T4 (hooks) |
| HookRegistry | T4 |
| auto_memory flag | T2 |
| EvolutionScheduler assembly | T4 |
| SSE endpoint | T6 |
| 4 new endpoints (events/by-turn/profile/summary) | T5 (3 non-SSE) + T6 (SSE) |
| IPC mappings (11 cmds) | T1 |
| Settings toggle UI C | T2 |
| Sidebar Memory entry UI A | T5 |
| Memory page UI A+D | T5 |
| Chat highlight_turn | T5 |
| source_turn_id traceability | T4 (schema) + T5 (UI) |
| Memory category extraction | T4 |
| Session-end watchdog | T4 |
| Testing strategy | Each task has tests |

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later" found. All step code blocks contain real content. Path params extraction, extractPathParams helper, polling fallback — all concrete.

**3. Type consistency:** Checked
- `MemoryLifecycleManager.is_auto_memory_enabled` → used in T2, T4
- `HookRegistry.on/off/emit/emit_sync` → T4 defines, T6 adds `emit_sync`
- `MemoryWriteEvent` dataclass fields → consistent across T4 + T6 SSE payload
- `MemoryAdapter.find_by_turn` / `find_by_category` / `find_by_category_and_session` → defined T5 Step 4, used T5 Step 5
- `EpisodicMemory.store(source_turn_id, ...)` → T4 Step 10; consumed by `MemoryAdapter.store` and `MemoryManager.remember` (T4 Steps 11-12)
- IPC cmd names → consistent across `commands.ts` (T1) and `preload.ts` (T1, T6)

**4. Spec requirement gaps:**
- Performance budget < 3% → documented in spec, plan respects (no extra LLM calls in hot path)
- Backward compat (default `auto_memory=True`) → T2 Step 3 default
- Win7 py3.8 compatibility → noted in spec as cherry-pick concern, plan is forward-only; cherry-pick strategy outside this plan's scope (handled by user's release process)

No inline fixes needed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-auto-memory-wiring.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration with quality gates
2. **Inline Execution** - I execute tasks in this session using executing-plans, batch execution with checkpoints for review

Which approach?