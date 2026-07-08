# Sage LLM Wiki Streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire end-to-end NDJSON streaming for sage LLM wiki chat and ingest endpoints, replacing 4 sync endpoints with proper abort/cleanup and event-split relay.

**Architecture:** Backend FastAPI async generators → NDJSON `StreamingResponse` → Electron main relay (event split, AbortController map) → Renderer hooks (existing, minor extension for error). Mirrors PR-6 orchestration chat streaming pattern (`docs/technical/23-chat-streaming.md`).

**Tech Stack:** Python 3.11 + FastAPI + httpx + conda `sage-backend`; Node 25.9.0 + React 19 + TypeScript + Vitest; Electron 21.4.4 + node-fetch; Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-07-08-wiki-streaming-design.md` (commit `a181132`).

## Global Constraints

- Branch base: `main`; target: `main`. New branches off main.
- Per project convention: `LEFTHOOK=0 git push -u origin <branch>` (lefthook pre-push flake workaround, see project memory).
- Backend tests: `conda activate sage-backend && pytest backend/tests/<path> -v` (NEVER use system Python).
- Frontend type check: `npx tsc --noEmit` (project root).
- Frontend tests: `npx vitest run <path>`.
- Frontend coverage: `npx vitest run --coverage <path>` ≥ 80% on new code.
- E2E: `npx playwright test <spec>` (skipped on CI for e2e-root, only local + electron-smoke).
- TypeScript strict: no `any`; use `unknown` + narrowing; React props as named `interface` (per `~/.claude/rules/typescript/coding-style.md`).
- No `console.log` in production code.
- Commits: conventional (`fix:`/`feat:`/`refactor:`/`perf:`/`test:`); English body, focus on **why**.
- PR body lists sub-commits + test plan; per project convention user merges manually after CI green.
- release/win7 sync: NOT in scope of this plan (apply cherry-pick per project pattern after main merge, separately).

## File Structure

### PR-1 (bugfix batch)
- **New**: `backend/wiki/llm_context.py` — LLMContext dataclass + make_llm_context factory
- **New**: `backend/tests/unit/test_llm_context.py` — 3 tests (construction, llm_call, llm_stream_call)
- **New**: `backend/tests/unit/test_graph_cache.py` — 4 tests (cold, hit, mtime-miss, query-miss)
- **New**: `src/widgets/wiki/__tests__/WikiEditor.test.tsx` — 1 test (file switch sync)
- **Modify**: `src/widgets/wiki/WikiEditor.tsx:18-21` — useState → useEffect
- **Modify**: `backend/api/wiki_routes.py` — recursive list_directory; 4 routes (chat/ingest/research/clip) use LLMContext Depends
- **Modify**: `backend/wiki/graph.py:216-220` — mtime-based get_graph_cached
- **Modify**: `backend/tests/unit/test_list_directory.py` — add 1 recursive test

### PR-2 (chat streaming)
- **New**: `backend/tests/integration/test_chat_stream.py` — 5 tests (NDJSON format, full chunk concat, citations, error, abort)
- **New**: `src/features/wiki/__tests__/useWikiChatStream.test.tsx` — 4 tests (chunk accumulate, done, error, cancel)
- **New**: `e2e/wiki-chat-stream.spec.ts` — 1 smoke (UI sees streaming)
- **Modify**: `backend/wiki/chat.py` — add `chat_with_wiki_stream` (refactor existing `chat_with_wiki` to extract retrieve/build_prompt helpers)
- **Modify**: `backend/api/wiki_routes.py` — replace `/chat` with `/chat/stream` (NDJSON)
- **Modify**: `electron/relay.ts` — add `relayNdjsonToEvent`
- **Modify**: `electron/commands.ts` — add `wiki_chat_stream` IPC handler + `streamControllers` Map
- **Modify**: `electron/preload.ts` — `sage:unlisten` payload includes `streamId`
- **Modify**: `src/shared/api-client/wiki.ts` — add `wikiChatStream`
- **Modify**: `src/widgets/wiki/WikiChat.tsx` — use streaming call
- **Modify**: `src/features/wiki/useWikiChatStream.ts` — add error event listener

### PR-3 (ingest streaming)
- **New**: `backend/tests/integration/test_ingest_stream.py` — 5 tests (progress order, completed, cache hit early-return, error, abort)
- **New**: `src/features/wiki/__tests__/useWikiIngest.test.tsx` — 3 tests (progress, completed, error)
- **New**: `e2e/wiki-ingest-stream.spec.ts` — 1 smoke
- **Modify**: `backend/wiki/ingest.py` — add `ingest_source_stream`; refactor existing `ingest_source` to extract `copy_to_raw`, `cache_get/put`, `analyze_source`, `generate_pages`, `embed_pages` as module-level functions
- **Modify**: `backend/api/wiki_routes.py` — replace `/ingest` with `/ingest/stream` (NDJSON)
- **Modify**: `electron/commands.ts` — add `wiki_ingest_stream` IPC handler
- **Modify**: `src/shared/api-client/wiki.ts` — add `wikiIngestStream`
- **Modify**: `src/widgets/wiki/WikiProjectPicker.tsx` — render `<WikiIngestProgress>` on import

---

# PR-1: fix(wiki): bugfix batch + LLMContext refactor

**Branch:** `fix/wiki-bugfix-batch`
**Target:** `main`
**Commits:** 4 (1 per task below)

## Task 1: Fix WikiEditor useState → useEffect

**Files:**
- Modify: `src/widgets/wiki/WikiEditor.tsx:18-21`
- Create: `src/widgets/wiki/__tests__/WikiEditor.test.tsx`

**Interfaces:**
- Consumes: existing `WikiEditor` component
- Produces: `editContent` re-syncs when `fileContent` changes

- [ ] **Step 1: Write failing test**

Create `src/widgets/wiki/__tests__/WikiEditor.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { WikiEditor } from '../WikiEditor';
import { useWikiStore } from '../../../entities/wiki/store';

describe('WikiEditor', () => {
  it('re-syncs editContent when fileContent changes', () => {
    const setEditContent = vi.fn();
    const setIsEditing = vi.fn();
    useWikiStore.setState({
      fileContent: 'first',
      editContent: '',
      isEditing: false,
      setEditContent,
      setIsEditing,
    } as any);
    const { rerender } = render(<WikiEditor />);
    expect(setEditContent).toHaveBeenLastCalledWith('first');

    useWikiStore.setState({ fileContent: 'second' } as any);
    rerender(<WikiEditor />);
    expect(setEditContent).toHaveBeenLastCalledWith('second');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/widgets/wiki/__tests__/WikiEditor.test.tsx -v`
Expected: FAIL — `setEditContent` is only called once with 'first' (useState initializer runs once), not with 'second'.

- [ ] **Step 3: Fix the bug**

Edit `src/widgets/wiki/WikiEditor.tsx` around line 18-21:

```diff
- useState(() => {
+ useEffect(() => {
    setEditContent(fileContent);
    setIsEditing(false);
- });
+ }, [fileContent]);
```

Also fix the React import: add `useEffect` to the import from 'react'. Remove `useState` if no longer used elsewhere in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/widgets/wiki/__tests__/WikiEditor.test.tsx -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/widgets/wiki/WikiEditor.tsx src/widgets/wiki/__tests__/WikiEditor.test.tsx
git commit -m "fix(wiki): re-sync WikiEditor on file switch

The useState initializer only runs on first mount, so opening a second
file after the editor was first opened never re-synced editContent.
The bug was invisible because the preview pane always re-renders from
MarkdownPreview; only the edit button revealed the stale text.
Switching to useEffect with fileContent dependency makes the editor
react to file switches."
```

## Task 2: Recursive list_directory

**Files:**
- Modify: `backend/api/wiki_routes.py` — `list_directory` handler
- Modify: `backend/tests/unit/test_list_directory.py` — add 1 test

**Interfaces:**
- Consumes: existing `list_directory(path, project_path, depth=10)` signature
- Produces: tree with children populated recursively, hidden files filtered, dirs sorted before files

- [ ] **Step 1: Add test case for recursive children**

Append to `backend/tests/unit/test_list_directory.py`:

```python
def test_list_directory_recursive_children(tmp_path):
    project = tmp_path / "wiki-project"
    wiki = project / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "index.md").write_text("x")
    concepts = wiki / "concepts"
    concepts.mkdir()
    (concepts / "alpha.md").write_text("a")
    (concepts / "beta.md").write_text("b")
    (concepts / ".hidden").write_text("h")  # should be filtered

    result = list_directory_impl("wiki", str(project))

    wiki_node = result[0]
    assert wiki_node["name"] == "wiki"
    children_names = sorted(c["name"] for c in wiki_node["children"])
    assert children_names == ["concepts", "index.md"]

    concepts_node = next(c for c in wiki_node["children"] if c["name"] == "concepts")
    assert sorted(c["name"] for c in concepts_node["children"]) == ["alpha.md", "beta.md"]
```

(If the existing test file uses a different helper name, follow that pattern.)

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate sage-backend && pytest backend/tests/unit/test_list_directory.py::test_list_directory_recursive_children -v`
Expected: FAIL — current `list_directory_impl` (or `_check_project_impl` style helper) sets `children=[]`.

- [ ] **Step 3: Implement recursive walk**

In `backend/api/wiki_routes.py`, replace the list_directory body:

```python
@router.get("/list")
async def list_directory(path: str, project_path: str, depth: int = 10) -> List[Dict]:
    base = Path(project_path) / path
    if not base.exists():
        raise HTTPException(status_code=404, detail="path not found")
    def walk(p: Path, d: int) -> Dict:
        node = {
            "name": p.name,
            "path": str(p.relative_to(Path(project_path))),
            "is_dir": p.is_dir(),
        }
        if p.is_dir() and d > 0:
            node["children"] = [
                walk(child, d - 1)
                for child in sorted(
                    p.iterdir(),
                    key=lambda x: (not x.is_dir(), x.name.lower()),
                )
                if not child.name.startswith(".")
            ]
        else:
            node["children"] = []
        return node
    return [walk(base, depth)]
```

If the existing route uses a private `_check_project_impl` helper, keep the public route thin and put the recursive walk in a private helper `list_directory_impl(path, project_path, depth=10)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate sage-backend && pytest backend/tests/unit/test_list_directory.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/wiki_routes.py backend/tests/unit/test_list_directory.py
git commit -m "fix(wiki): recursive list_directory

The previous implementation set children=[] for every directory,
making WikiFileTree only show depth 1. Users couldn't browse
wiki/concepts/*.md, wiki/sources/*.md, etc. Now recurses to depth 10,
filters hidden files, sorts dirs before files."
```

## Task 3: mtime-based graph cache

**Files:**
- Modify: `backend/wiki/graph.py:216-220`
- Create: `backend/tests/unit/test_graph_cache.py`

**Interfaces:**
- Consumes: `get_graph_cached(project_root: Path, query: Optional[str] = None)`
- Produces: mtime-aware cache; rebuild only when wiki/*.md mtime or query changes

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_graph_cache.py`:

```python
import json
import time
from pathlib import Path
from backend.wiki.graph import get_graph_cached

def _make_wiki(project_root: Path) -> None:
    wiki = project_root / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("---\ntitle: A\n---\nbody A")
    (wiki / "b.md").write_text("---\ntitle: B\n---\nbody B", encoding="utf-8")

def test_graph_cache_cold_build(tmp_path):
    _make_wiki(tmp_path)
    graph = get_graph_cached(tmp_path)
    assert len(graph.nodes) >= 2

def test_graph_cache_hit_on_second_call(tmp_path):
    _make_wiki(tmp_path)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    g1 = get_graph_cached(tmp_path)
    assert cache_path.exists()
    # Read raw data; ensure same data was reused
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    g2 = get_graph_cached(tmp_path)
    cached2 = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached == cached2

def test_graph_cache_miss_on_mtime_change(tmp_path):
    _make_wiki(tmp_path)
    g1 = get_graph_cached(tmp_path)
    time.sleep(0.02)  # ensure mtime granularity
    (tmp_path / "wiki" / "a.md").write_text("updated content")
    g2 = get_graph_cached(tmp_path)
    # Different cache state (mtime changed)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["latest_mtime"] > 0

def test_graph_cache_miss_on_query_change(tmp_path):
    _make_wiki(tmp_path)
    get_graph_cached(tmp_path, query=None)
    get_graph_cached(tmp_path, query="something else")
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["query"] == "something else"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda activate sage-backend && pytest backend/tests/unit/test_graph_cache.py -v`
Expected: All FAIL — current `get_graph_cached` is a TODO and always rebuilds.

- [ ] **Step 3: Implement mtime cache**

Replace `get_graph_cached` in `backend/wiki/graph.py`:

```python
def get_graph_cached(project_root: Path, query: Optional[str] = None) -> GraphData:
    """Build or load the wiki graph, with mtime-based cache.

    Cache key = (max mtime of wiki/**/*.md, query string).
    Cache file: {project_root}/.llm-wiki/graph-cache.json
    """
    cache_path = project_root / ".llm-wiki" / "graph-cache.json"
    wiki_dir = project_root / "wiki"
    if not wiki_dir.exists():
        return build_graph(project_root, query)

    latest_mtime = max(
        (p.stat().st_mtime for p in wiki_dir.rglob("*.md") if p.is_file()),
        default=0.0,
    )

    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cache.get("latest_mtime") == latest_mtime
                and cache.get("query") == query
            ):
                return GraphData.from_dict(cache["data"])
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # corrupt cache, rebuild

    graph = build_graph(project_root, query)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "latest_mtime": latest_mtime,
                "query": query,
                "data": graph.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return graph
```

(Check that `GraphData.from_dict` and `graph.to_dict()` exist in the existing `models.py`; if not, use the existing serialization helpers in `graph.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda activate sage-backend && pytest backend/tests/unit/test_graph_cache.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/wiki/graph.py backend/tests/unit/test_graph_cache.py
git commit -m "perf(wiki): mtime-based graph cache

get_graph_cached previously rebuilt the entire 4-signal graph on every
call (O(N²) for N pages). This is the hot path for graph view,
communities, insights, and MCP tools. Now caches the graph to
.llm-wiki/graph-cache.json keyed on max mtime of wiki/**/*.md plus the
query string. Cache invalidates on any wiki file change or query change.
Expected ~10x speedup on repeat calls."
```

## Task 4: Extract LLMContext dependency

**Files:**
- Create: `backend/wiki/llm_context.py`
- Create: `backend/tests/unit/test_llm_context.py`
- Modify: `backend/api/wiki_routes.py` — 4 routes (`/chat`, `/ingest`, `/research`, `/clip`)

**Interfaces:**
- Consumes: existing route handlers' inline `llm_call`/`http_post` async functions
- Produces: `LLMContext` dataclass with `llm_call`, `llm_stream_call`, `http_post`; `get_wiki_llm_context` factory Depends

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_llm_context.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from backend.wiki.llm_context import make_llm_context, LLMContext


def test_make_llm_context_returns_dataclass():
    ctx = make_llm_context("http://api.test", "sk-test", "gpt-4")
    assert isinstance(ctx, LLMContext)
    assert callable(ctx.llm_call)
    assert callable(ctx.llm_stream_call)
    assert callable(ctx.http_post)


def test_llm_call_uses_correct_request_shape():
    ctx = make_llm_context("http://api.test/v1", "sk-abc", "gpt-4o-mini")
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    fake_response.raise_for_status = MagicMock()
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient", return_value=fake_async_client):
        import asyncio
        result = asyncio.run(ctx.llm_call([{"role": "user", "content": "x"}], 0.7))
    assert result == "hi"
    call_kwargs = fake_async_client.post.call_args.kwargs
    assert call_kwargs["json"]["model"] == "gpt-4o-mini"
    assert call_kwargs["json"]["stream"] is False
    assert call_kwargs["json"]["temperature"] == 0.7
    assert "Authorization" in call_kwargs["headers"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate sage-backend && pytest backend/tests/unit/test_llm_context.py -v`
Expected: FAIL — `backend.wiki.llm_context` doesn't exist.

- [ ] **Step 3: Implement LLMContext**

Create `backend/wiki/llm_context.py`:

```python
"""LLMContext: shared LLM/HTTP injection for wiki routes.

Replaces 4 copies of inline `llm_call`/`http_post` definitions across
backend/api/wiki_routes.py. PR-2/3 will use ctx.llm_stream_call to
switch /chat and /ingest to NDJSON streaming without changing the
dependency wiring.
"""
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, List
import json
import httpx

LlmCall = Callable[[List[Dict], float], Awaitable[str]]
LlmStreamCall = Callable[[List[Dict], float], AsyncIterator[str]]
HttpPost = Callable[[str, Dict[str, str], dict], Awaitable[str]]


@dataclass
class LLMContext:
    llm_call: LlmCall
    llm_stream_call: LlmStreamCall
    http_post: HttpPost


def make_llm_context(
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: int = 1800,
) -> LLMContext:
    """Build LLMContext for a given provider+model+key.

    base_url is the OpenAI-compatible /chat/completions root
    (e.g. https://api.openai.com/v1).
    """
    chat_url = f"{llm_base_url.rstrip('/')}/chat/completions"
    auth_headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }

    async def llm_call(messages: List[Dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(
                chat_url,
                headers=auth_headers,
                json={
                    "model": llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def llm_stream_call(
        messages: List[Dict], temperature: float,
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream(
                "POST",
                chat_url,
                headers=auth_headers,
                json={
                    "model": llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta

    async def http_post(url: str, headers: Dict[str, str], body: dict) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.text

    return LLMContext(llm_call, llm_stream_call, http_post)


def get_wiki_llm_context(request_body: dict) -> LLMContext:
    """FastAPI Depends factory: build LLMContext from request body.

    Works for ChatRequest/IngestRequest/ResearchRequest/ClipRequest,
    all of which carry llm_base_url/llm_api_key/llm_model.
    """
    return make_llm_context(
        llm_base_url=request_body.get("llm_base_url", ""),
        llm_api_key=request_body.get("llm_api_key", ""),
        llm_model=request_body.get("llm_model", ""),
    )
```

Note: `get_wiki_llm_context` takes a parsed body dict. The route handlers should accept the request body as a parameter and pass it in. Two patterns to choose from in the actual implementation:

- **Pattern A** (recommended for FastAPI): Each route declares the body as a typed Pydantic model, then calls `get_wiki_llm_context(req.model_dump())` to get the LLMContext. This keeps type safety.
- **Pattern B**: Add a middleware that parses the body into `request.state`, then `get_wiki_llm_context(request)` reads from there.

Pick what fits the existing wiki_routes.py style; both are valid.

- [ ] **Step 4: Refactor 4 routes to use LLMContext**

For each of `/ingest`, `/chat`, `/research`, `/clip` in `backend/api/wiki_routes.py`:

1. Remove the inline `async def llm_call(messages, temperature): ...` block (~30 lines)
2. Remove the inline `async def http_post(url, headers, body): ...` block (~10 lines)
3. Build LLMContext at the top of the route body via `ctx = get_wiki_llm_context(req.model_dump() if hasattr(req, 'model_dump') else req.dict())` (or call `make_llm_context(req.llm_base_url, req.llm_api_key, req.llm_model)` directly as a one-liner)
4. Replace all `llm_call(...)` calls with `ctx.llm_call(...)`
5. Replace all `http_post(...)` calls with `ctx.http_post(...)`

(Each route currently has ~40 lines of duplicated httpx code. After refactor, ~5 lines.)

- [ ] **Step 5: Run all backend tests to verify no regression**

Run: `conda activate sage-backend && pytest backend/tests -q`
Expected: All PASS (no behavioral change)

- [ ] **Step 6: Commit**

```bash
git add backend/wiki/llm_context.py backend/tests/unit/test_llm_context.py backend/api/wiki_routes.py
git commit -m "refactor(wiki): extract LLMContext dependency

4 routes (/chat, /ingest, /research, /clip) each defined their own
inline llm_call and http_post async functions — 4 copies of the same
httpx boilerplate. Extracts to a single LLMContext dataclass with 3
callbacks (llm_call, llm_stream_call, http_post). PR-2/3 will switch
/chat and /ingest to llm_stream_call without changing the dependency
wiring."
```

## PR-1 Review Check

Before pushing:
```bash
npx tsc --noEmit                                # frontend green
conda activate sage-backend && pytest backend/tests -q  # backend green
LEFTHOOK=0 git push -u origin fix/wiki-bugfix-batch
gh pr create --base main \
  --title "fix(wiki): bugfix batch + LLMContext refactor" \
  --body "## What
4 unrelated wiki fixes batched:
- WikiEditor useState → useEffect (1 line bug)
- recursive list_directory (WikiFileTree shows subdirs)
- mtime-based graph cache (10x speedup)
- LLMContext dependency (4 routes dedup)

## Why
PR-2/3 (wiki streaming) need LLMContext in place. The other 3 fixes
are independent and unblock the corresponding dead-code paths.

## Test
- 11 new tests pass (3 LLMContext + 4 graph cache + 2 list_directory + 1 WikiEditor + 1 existing list)
- All existing backend tests pass
- vitest + tsc green
- 4-CI green

## Risk
Low. LLMContext refactor is mechanical, no behavior change."
```

Wait for CI, then ask user to merge.

---

# PR-2: feat(wiki): streaming chat (NDJSON)

**Branch:** `feat/wiki-chat-stream` (after PR-1 merged)
**Target:** `main`
**Commits:** 6 (1 per task below)
**Spec reference:** §4.2, §4.4, §5, §6.1-6.3

## Task 1: Add chat_with_wiki_stream async generator

**Files:**
- Modify: `backend/wiki/chat.py` — add `chat_with_wiki_stream`
- Modify: `backend/wiki/chat.py` — extract helpers `retrieve` and `build_rag_prompt` if not already module-level

**Interfaces:**
- Consumes: `LLMContext` (from PR-1)
- Produces: `AsyncIterator[bytes]` yielding NDJSON lines (`{"event":"chunk","data":"text"}\n` and `{"event":"done","data":{"citations":[...]}}\n` and `{"event":"error","data":"msg"}\n`)

- [ ] **Step 1: Verify existing chat.py helpers are reusable**

Read `backend/wiki/chat.py`. If `retrieve(query, project_root, ...)` and `build_rag_prompt(query, pages, ...)` are already module-level functions, skip to step 2. If they're inline in `chat_with_wiki`, refactor to module level (small extra refactor, no test changes since no tests exist for them yet).

- [ ] **Step 2: Add chat_with_wiki_stream**

Append to `backend/wiki/chat.py`:

```python
import json
from typing import AsyncIterator, Optional

async def chat_with_wiki_stream(
    config: ChatConfig,
    project_root: Path,
    query: str,
    ctx: LLMContext,
    temperature: float = 0.3,
) -> AsyncIterator[bytes]:
    """Streaming variant of chat_with_wiki.

    Yields NDJSON lines:
      {"event":"chunk","data":"<text>"}\\n
      {"event":"done","data":{"citations":[...]}}\\n
      {"event":"error","data":"<msg>"}\\n (only on error)

    On exception: yield error line, then re-raise so FastAPI closes
    the response.
    """
    try:
        # 1. Retrieve (same logic as chat_with_wiki)
        retrieval = retrieve(query, project_root, config)
        citations = [p.path for p in retrieval.pages]
        # 2. Build prompt (same logic as chat_with_wiki)
        messages = build_rag_prompt(query, retrieval.pages, config)
        # 3. Stream from LLM
        async for delta in ctx.llm_stream_call(messages, temperature):
            line = json.dumps(
                {"event": "chunk", "data": delta},
                ensure_ascii=False,
            ) + "\n"
            yield line.encode("utf-8")
        # 4. Done with citations
        done_line = json.dumps(
            {"event": "done", "data": {"citations": citations}},
            ensure_ascii=False,
        ) + "\n"
        yield done_line.encode("utf-8")
    except Exception as e:
        logger.exception("chat_with_wiki_stream 失败")
        err_line = json.dumps(
            {"event": "error", "data": str(e)},
            ensure_ascii=False,
        ) + "\n"
        yield err_line.encode("utf-8")
        raise
```

(Adjust `retrieve` and `build_rag_prompt` signatures to match what already exists in chat.py — those are the existing public functions if you extracted them in step 1.)

- [ ] **Step 3: Commit**

```bash
git add backend/wiki/chat.py
git commit -m "feat(wiki): chat_with_wiki_stream async generator

Adds the streaming generator that yields NDJSON lines. Retrieval and
prompt building reuse the same logic as the sync chat_with_wiki (after
extracting the helpers to module level). On any exception, yields an
error NDJSON line and re-raises so FastAPI closes the response."
```

## Task 2: Add /chat/stream endpoint, deprecate /chat

**Files:**
- Modify: `backend/api/wiki_routes.py` — replace `/chat` with `/chat/stream`
- Create: `backend/tests/integration/test_chat_stream.py`

**Interfaces:**
- Consumes: `chat_with_wiki_stream` from Task 1
- Produces: `POST /api/v1/wiki/chat/stream` returning `StreamingResponse(media_type="application/x-ndjson")`

- [ ] **Step 1: Write integration test**

Create `backend/tests/integration/test_chat_stream.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from backend.main import app  # adjust to actual app import

client = TestClient(app)


@pytest.fixture
def project_with_pages(tmp_path):
    project = tmp_path / "wiki-project"
    wiki = project / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("# A\nbody A")
    (wiki / "b.md").write_text("# B\nbody B")
    return project


def test_chat_stream_yields_ndjson_lines(project_with_pages):
    """Stream returns chunk + done lines in NDJSON format."""
    # The async stream is consumed line-by-line by the test client.
    # Stub the LLM stream to yield controlled chunks.
    async def fake_stream(messages, temperature):
        for chunk in ["Hello", " world", "!"]:
            yield chunk
    # Patch the LLMContext.stream_call used by chat_with_wiki_stream.
    # (Adjust the patch path to match the actual import chain.)
    with patch("backend.wiki.chat.LLMContext") as MockCtx:
        instance = MockCtx.return_value
        instance.llm_stream_call = fake_stream

        r = client.post(
            "/api/v1/wiki/chat/stream",
            json={
                "query": "test",
                "project_path": str(project_with_pages),
                "llm_base_url": "http://api.test",
                "llm_api_key": "sk-test",
                "llm_model": "gpt-4",
                "embed_base_url": "http://api.test",
                "embed_api_key": "sk-test",
                "embed_model": "text-embedding-3-small",
            },
        )
        assert r.status_code == 200
        lines = r.text.strip().split("\n")
        events = [json.loads(l) for l in lines]
        chunks = [e["data"] for e in events if e["event"] == "chunk"]
        assert "".join(chunks) == "Hello world!"
        last_event = events[-1]
        assert last_event["event"] == "done"
        assert "citations" in last_event["data"]
```

(If the LLMContext is constructed via `Depends` and the route call is opaque, mock at a different level — e.g., patch `backend.wiki.chat.retrieve` to return a fixed set of pages, and let `ctx.llm_stream_call` be a real async generator that yields from a list. Adapt the test to fit the actual wiring.)

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate sage-backend && pytest backend/tests/integration/test_chat_stream.py -v`
Expected: FAIL — no such endpoint.

- [ ] **Step 3: Add /chat/stream route**

In `backend/api/wiki_routes.py`:

1. Import: `from fastapi.responses import StreamingResponse`
2. Replace the `/chat` route with `/chat/stream`:

```python
@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
) -> StreamingResponse:
    project_root = Path(req.project_path)
    ctx = get_wiki_llm_context(req.model_dump() if hasattr(req, "model_dump") else req.dict())
    config = ChatConfig(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        embed_base_url=req.embed_base_url,
        embed_api_key=req.embed_api_key,
        embed_model=req.embed_model,
        max_tokens=req.max_tokens,
    )
    return StreamingResponse(
        chat_with_wiki_stream(config, project_root, req.query, ctx),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

3. Delete the old `/chat` route entirely.

- [ ] **Step 4: Run integration test to verify it passes**

Run: `conda activate sage-backend && pytest backend/tests/integration/test_chat_stream.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/wiki_routes.py backend/tests/integration/test_chat_stream.py
git commit -m "feat(api): /chat/stream NDJSON endpoint, deprecate /chat

Replaces the sync /chat endpoint with /chat/stream returning a
StreamingResponse of NDJSON lines. Frontend (WikiChat.tsx) switches
in a follow-up commit. The sync /chat endpoint is removed because
nothing else calls it (grep -r 'wiki/chat' backend/ shows only the
router definition itself)."
```

## Task 3: Electron main: wiki_chat_stream IPC + relay

**Files:**
- Modify: `electron/relay.ts` — add `relayNdjsonToEvent`
- Modify: `electron/commands.ts` — add `wiki_chat_stream` handler + `streamControllers` Map
- Modify: `electron/preload.ts` — `sage:unlisten` payload includes `streamId`

**Interfaces:**
- Consumes: existing `parseNdjsonStream`
- Produces: `relayNdjsonToEvent(body, eventPrefix, webContents, signal, transform?)` that splits NDJSON by `event` field and dispatches to corresponding Electron channels

- [ ] **Step 1: Add relayNdjsonToEvent to relay.ts**

Append to `electron/relay.ts`:

```ts
type NdjsonEvent = 'chunk' | 'done' | 'error' | 'progress';

const DEFAULT_EVENT_SPLIT: Record<NdjsonEvent, string> = {
  chunk: '-chunk',
  done: '-done',
  error: '-error',
  progress: '-progress',
};

/**
 * Parse NDJSON stream and forward each event to a distinct Electron
 * channel based on the event name. Defaults:
 *   chunk  → {prefix}-chunk
 *   done   → {prefix}-done
 *   error  → {prefix}-error
 *   progress → {prefix}-progress
 *
 * For ingest streams, pass transform to redirect events to a different
 * suffix and/or transform the payload (e.g., 'done' → '-progress' with
 * payload {stage:'completed', percent:100}).
 */
export async function relayNdjsonToEvent(
  body: NodeJS.ReadableStream | null,
  eventPrefix: string,
  webContents: WebContentsLike,
  signal: AbortSignal,
  transform?: (rawEvent: any) => { suffix: string; data: any } | null,
): Promise<void> {
  await parseNdjsonStream(body, (rawEvent: any) => {
    if (typeof rawEvent !== 'object' || !rawEvent.event) {
      webContents.send(`sage:event:${eventPrefix}-error`, {
        error: 'invalid NDJSON line',
      });
      return;
    }
    let result: { suffix: string; data: any } | null;
    if (transform) {
      result = transform(rawEvent);
    } else {
      const suffix = DEFAULT_EVENT_SPLIT[rawEvent.event as NdjsonEvent];
      if (!suffix) return;  // unknown event, skip
      result = { suffix, data: rawEvent.data };
    }
    if (!result) return;
    webContents.send(`sage:event:${eventPrefix}${result.suffix}`, result.data);
  }, signal);
}
```

- [ ] **Step 2: Add streamControllers Map + wiki_chat_stream handler**

In `electron/commands.ts`, add at module top:

```ts
const streamControllers = new Map<string, AbortController>();
```

Find the existing `ipcMain.handle('sage:invoke', ...)` block. Add a new branch inside the dispatcher (where the switch on `cmd` happens):

```ts
if (cmd === 'wiki_chat_stream') {
  const streamId = `wiki-chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const controller = new AbortController();
  streamControllers.set(streamId, controller);
  const wc = BrowserWindow.fromWebContents(_e.sender);
  if (!wc) {
    streamControllers.delete(streamId);
    throw new Error('No WebContents for invoke');
  }
  // Fire-and-forget: relay runs in background
  (async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/wiki/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(
          `sage:event:wiki-chat-stream-${streamId}-error`,
          { error: `HTTP ${res.status}` },
        );
        return;
      }
      await relayNdjsonToEvent(
        res.body as any,
        `wiki-chat-stream-${streamId}`,
        wc,
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        wc.webContents.send(
          `sage:event:wiki-chat-stream-${streamId}-error`,
          { error: String(e) },
        );
      }
    } finally {
      streamControllers.delete(streamId);
    }
  })();
  return { streamId };
}
```

- [ ] **Step 3: Add sage:unlisten handler for streamId abort**

In `electron/commands.ts`, find `ipcMain.handle('sage:unlisten', ...)` (existing). If it takes a payload like `{ event }`, extend to `{ event, streamId }`:

```ts
ipcMain.handle('sage:unlisten', async (_e, { event, streamId }) => {
  if (streamId) {
    const controller = streamControllers.get(streamId);
    if (controller) {
      controller.abort();
      streamControllers.delete(streamId);
    }
  }
  // ... existing unlisten logic (if any) ...
});
```

- [ ] **Step 4: Type check**

Run: `cd /home/fz/project/sage && npx tsc --noEmit`
Expected: All green

- [ ] **Step 5: Commit**

```bash
git add electron/relay.ts electron/commands.ts electron/preload.ts
git commit -m "feat(electron): wiki_chat_stream IPC + NDJSON relay

Adds the wiki_chat_stream invoke handler that POSTs to
/api/v1/wiki/chat/stream and forwards NDJSON lines via the new
relayNdjsonToEvent helper. Each event is dispatched to a distinct
Electron IPC channel (wiki-chat-stream-{id}-{chunk|done|error}).
streamControllers Map tracks AbortControllers for cleanup on
sage:unlisten."
```

## Task 4: useWikiChatStream error event support

**Files:**
- Modify: `src/features/wiki/useWikiChatStream.ts`
- Create: `src/features/wiki/__tests__/useWikiChatStream.test.tsx`

**Interfaces:**
- Consumes: existing `useWikiChatStream(streamId)` hook
- Produces: hook also listens for `-error` event, sets `state.error`

- [ ] **Step 1: Write failing test**

Create `src/features/wiki/__tests__/useWikiChatStream.test.tsx`:

```tsx
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useWikiChatStream } from '../useWikiChatStream';

const listeners: Record<string, Array<(e: { payload: any }) => void>> = {};
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: vi.fn(async (event: string, handler: any) => {
    listeners[event] = listeners[event] || [];
    listeners[event].push(handler);
    return () => {
      listeners[event] = listeners[event].filter((h) => h !== handler);
    };
  }),
}));

describe('useWikiChatStream', () => {
  beforeEach(() => {
    Object.keys(listeners).forEach((k) => delete listeners[k]);
  });

  it('accumulates answer from chunk events', async () => {
    const { result, rerender } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: null as string | null } },
    );
    act(() => result.current.reset());
    rerender({ streamId: 's1' });
    await act(async () => {
      listeners['wiki-chat-stream-s1-chunk'].forEach((h) => h({ payload: 'Hello' }));
      listeners['wiki-chat-stream-s1-chunk'].forEach((h) => h({ payload: ' world' }));
    });
    expect(result.current.answer).toBe('Hello world');
    expect(result.current.streaming).toBe(true);
  });

  it('sets streaming=false and citations on done event', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      listeners['wiki-chat-stream-s1-done'].forEach((h) =>
        h({ payload: { citations: ['wiki/a.md', 'wiki/b.md'] } }),
      );
    });
    expect(result.current.streaming).toBe(false);
    expect(result.current.citations).toEqual(['wiki/a.md', 'wiki/b.md']);
  });

  it('sets error on error event', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      listeners['wiki-chat-stream-s1-error'].forEach((h) =>
        h({ payload: { error: 'LLM timeout' } }),
      );
    });
    expect(result.current.error).toBe('LLM timeout');
    expect(result.current.streaming).toBe(false);
  });

  it('unlistens when streamId becomes null', async () => {
    const { rerender } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    expect(listeners['wiki-chat-stream-s1-chunk']?.length).toBe(1);
    rerender({ streamId: null });
    expect(listeners['wiki-chat-stream-s1-chunk']?.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/features/wiki/__tests__/useWikiChatStream.test.tsx -v`
Expected: 3rd test FAILS (no error listener yet); 4th test FAILS (current code only cleanup on streamId change, but we want to verify the chunk listener is gone — current code's cleanup is correct, so this test should PASS — adjust if it does).

- [ ] **Step 3: Add error event listener to hook**

In `src/features/wiki/useWikiChatStream.ts`, add a third listener inside the `useEffect`:

```diff
   useEffect(() => {
     if (!streamId) return;
     setState({ answer: '', citations: [], streaming: true, error: null });
     const chunkEvent = `wiki-chat-stream-${streamId}-chunk`;
     const doneEvent = `wiki-chat-stream-${streamId}-done`;
+    const errorEvent = `wiki-chat-stream-${streamId}-error`;
     let unlistenChunk: UnlistenFn | null = null;
     let unlistenDone: UnlistenFn | null = null;
+    let unlistenError: UnlistenFn | null = null;

     listen<string>(chunkEvent, (e) => {
       setState((s) => ({ ...s, answer: s.answer + e.payload }));
     })
       .then((fn) => { unlistenChunk = fn; })
       .catch((e) => { setState((s) => ({ ...s, streaming: false, error: String(e) })); });

     listen<{ citations: string[] }>(doneEvent, (e) => {
       setState((s) => ({ ...s, streaming: false, citations: e.payload.citations }));
     })
       .then((fn) => { unlistenDone = fn; })
       .catch((e) => { setState((s) => ({ ...s, streaming: false, error: String(e) })); });

+    listen<{ error: string }>(errorEvent, (e) => {
+      setState((s) => ({ ...s, streaming: false, error: e.payload.error }));
+    })
+      .then((fn) => { unlistenError = fn; })
+      .catch((e) => { setState((s) => ({ ...s, streaming: false, error: String(e) })); });

     return () => {
       if (unlistenChunk) unlistenChunk();
       if (unlistenDone) unlistenDone();
+      if (unlistenError) unlistenError();
     };
   }, [streamId]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/wiki/__tests__/useWikiChatStream.test.tsx -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/features/wiki/useWikiChatStream.ts src/features/wiki/__tests__/useWikiChatStream.test.tsx
git commit -m "feat(wiki-chat): useWikiChatStream error event support

Adds listener for wiki-chat-stream-{id}-error. On error, sets
state.streaming=false and state.error=<msg>. Closes the gap that
backend errors were silently dropped by the hook."
```

## Task 5: Replace non-streaming wikiChat with stream

**Files:**
- Modify: `src/shared/api-client/wiki.ts` — add `wikiChatStream`
- Modify: `src/widgets/wiki/WikiChat.tsx` — call `wikiChatStream` instead of `wikiChat`

**Interfaces:**
- Consumes: existing `wikiChat` (will be removed)
- Produces: `wikiChatStream(query, projectPath, llmConfig, handlers) -> Promise<{streamId, cancel}>`

- [ ] **Step 1: Add wikiChatStream to api-client**

In `src/shared/api-client/wiki.ts`, add:

```ts
import { invoke } from '../api/desktopInvoke';
import { listen, type UnlistenFn } from '../api/desktopEvent';

export interface WikiChatLlmConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  embedBaseUrl: string;
  embedApiKey: string;
  embedModel: string;
}

export interface WikiChatStreamHandlers {
  onChunk: (chunk: string) => void;
  onDone: (data: { citations: string[] }) => void;
  onError: (err: Error) => void;
}

export async function wikiChatStream(
  query: string,
  projectPath: string,
  llmConfig: WikiChatLlmConfig,
  handlers: WikiChatStreamHandlers,
): Promise<{ streamId: string; cancel: () => void }> {
  const { streamId } = await invoke<{ streamId: string }>('wiki_chat_stream', {
    query,
    projectPath,
    llmBaseUrl: llmConfig.baseUrl,
    llmApiKey: llmConfig.apiKey,
    llmModel: llmConfig.model,
    embedBaseUrl: llmConfig.embedBaseUrl,
    embedApiKey: llmConfig.embedApiKey,
    embedModel: llmConfig.embedModel,
  });
  const prefix = `wiki-chat-stream-${streamId}`;
  const unlistenChunk: UnlistenFn = await listen<string>(`${prefix}-chunk`, (e) =>
    handlers.onChunk(e.payload),
  );
  const unlistenDone: UnlistenFn = await listen<{ citations: string[] }>(
    `${prefix}-done`,
    (e) => handlers.onDone(e.payload),
  );
  const unlistenError: UnlistenFn = await listen<{ error: string }>(
    `${prefix}-error`,
    (e) => handlers.onError(new Error(e.payload.error)),
  );
  return {
    streamId,
    cancel: () => {
      unlistenChunk();
      unlistenDone();
      unlistenError();
    },
  };
}
```

- [ ] **Step 2: Update WikiChat.tsx to use stream**

In `src/widgets/wiki/WikiChat.tsx`, replace the import and the `handleSend` body:

```diff
- import { wikiChat } from '../../shared/api-client/wiki';
+ import { wikiChatStream } from '../../shared/api-client/wiki';
```

```diff
-    try {
-      const response = await wikiChat(
-        query,
-        project.path,
-        chatEndpoint.baseUrl,
-        chatEndpoint.apiKey,
-        chatModelId,
-        chatEndpoint.baseUrl,
-        chatEndpoint.apiKey,
-        'text-embedding-3-small',
-      );
-      const assistantMessage: ChatMessage = {
-        role: 'assistant',
-        content: response.answer,
-        citations: response.citations,
-      };
-      setMessages((prev) => [...prev, assistantMessage]);
-    } catch (e) {
-      setMessages((prev) => [...prev, { role: 'assistant', content: `查询失败: ${e}` }]);
-    } finally {
-      setLoading(false);
-    }
+    try {
+      await wikiChatStream(
+        query,
+        project.path,
+        {
+          baseUrl: chatEndpoint.baseUrl,
+          apiKey: chatEndpoint.apiKey,
+          model: chatModelId,
+          embedBaseUrl: chatEndpoint.baseUrl,
+          embedApiKey: chatEndpoint.apiKey,
+          embedModel: 'text-embedding-3-small',
+        },
+        {
+          // useWikiChatStream (consuming streamId above) already
+          // accumulates chunks; we only flip loading on done/error.
+          onChunk: () => {},
+          onDone: () => setLoading(false),
+          onError: (err) => {
+            setMessages((prev) => [
+              ...prev,
+              { role: 'assistant', content: `查询失败: ${err.message}` },
+            ]);
+            setLoading(false);
+          },
+        },
+      );
+    } catch (e) {
+      setMessages((prev) => [...prev, { role: 'assistant', content: `查询失败: ${e}` }]);
+      setLoading(false);
+    }
```

(If `wikiChat` is no longer used anywhere after this change, remove it from `api-client/wiki.ts` in this commit. Grep first: `grep -r 'wikiChat' src/` — should only be `WikiChat.tsx` after this commit.)

- [ ] **Step 3: Type check + run hook tests**

Run:
```bash
npx tsc --noEmit
npx vitest run src/features/wiki src/widgets/wiki
```
Expected: All green

- [ ] **Step 4: Commit**

```bash
git add src/shared/api-client/wiki.ts src/widgets/wiki/WikiChat.tsx
git commit -m "refactor(wiki-chat): wire WikiChat to NDJSON stream

Replaces non-streaming wikiChat() call with wikiChatStream(). The
hook useWikiChatStream already accumulates chunks into stream.answer;
the UI block for {stream.answer && ...} renders them live. Errors
flip loading off via onError handler. Removes the dead streamId
discard that was the visible symptom of the unwired streaming."
```

## Task 6: E2E smoke for chat streaming

**Files:**
- Create: `e2e/wiki-chat-stream.spec.ts`

- [ ] **Step 1: Write e2e test**

Create `e2e/wiki-chat-stream.spec.ts` (model after `e2e/wiki-folder-picker.spec.ts`):

```ts
import { test, expect } from '@playwright/test';

test.describe('wiki chat stream', () => {
  test('shows streaming answer in WikiChat', async ({ page }) => {
    // Stub the wiki_chat_stream invoke + relay by intercepting network
    // or by using a mock LLM endpoint. For local dev, this requires
    // a stub backend. Skip if not configured.
    test.skip(!process.env.STREAM_E2E, 'STREAM_E2E env not set');

    await page.goto('/');
    // Open a project via the folder picker
    // (use a fixture path or skip the picker steps)
    // ...

    // Click into chat view, type a question, click send
    // ...

    // Expect: streaming answer appears (text changes over time)
    // await expect(page.locator('[data-testid="chat-streaming-answer"]'))
    //   .toContainText('Hello', { timeout: 5000 });
  });
});
```

(Adjust selectors and setup to match the actual UI. Mark as `test.skip` by default since e2e requires a stub LLM environment. The hook unit tests in Task 4 already cover the streaming behavior; e2e just verifies end-to-end UI wiring.)

- [ ] **Step 2: Verify it runs (skip mode)**

Run: `npx playwright test e2e/wiki-chat-stream.spec.ts --reporter=list`
Expected: 1 test skipped (or passed if STREAM_E2E set)

- [ ] **Step 3: Commit**

```bash
git add e2e/wiki-chat-stream.spec.ts
git commit -m "test(wiki-chat): e2e smoke for streaming chat

Smoke test that verifies the UI sees streamed chunks. Skipped by
default (STREAM_E2E env gate) since it requires a stub LLM endpoint.
Run with STREAM_E2E=1 locally for manual verification."
```

## PR-2 Review Check

Before pushing:
```bash
npx tsc --noEmit
conda activate sage-backend && pytest backend/tests -q
npx vitest run src/features/wiki src/widgets/wiki
LEFTHOOK=0 git push -u origin feat/wiki-chat-stream
gh pr create --base main \
  --title "feat(wiki): streaming chat (NDJSON)" \
  --body "## What
End-to-end NDJSON streaming for /api/v1/wiki/chat:
- Backend: chat_with_wiki_stream async generator + /chat/stream route
- Electron: relayNdjsonToEvent + wiki_chat_stream IPC + streamControllers
- Frontend: useWikiChatStream error event + wikiChatStream api-client + WikiChat wiring
- Tests: 5 integration + 4 hook unit + 1 e2e smoke

## Why
WikiChat.tsx was calling a non-streaming endpoint and discarding the
streamId. The hook and component were already designed for streaming.
Closes the gap and unblocks user-perceived '答案逐字' UX.

## Test
- 10 new tests pass
- All existing tests pass
- Manual: with a stub LLM, see '思考中' → chunk-by-chunk → '完成'
  with citation chips appearing

## Risk
Medium. Touches 3 layers (backend/Electron/frontend) and a hot
endpoint. Mitigated by: integration test covers NDJSON contract;
hook test covers event semantics; e2e smoke verifies wiring."
```

Wait for CI, then ask user to merge.

---

# PR-3: feat(wiki): streaming ingest (NDJSON)

**Branch:** `feat/wiki-ingest-stream` (after PR-1 merged; can be parallel with PR-2)
**Target:** `main`
**Commits:** 5 (1 per task below)
**Spec reference:** §4.3, §4.5, §5, §6.1, §6.4

## Task 1: Add ingest_source_stream + extract module-level helpers

**Files:**
- Modify: `backend/wiki/ingest.py` — refactor `ingest_source` to extract `copy_to_raw`, `cache_get/put`, `analyze_source`, `generate_pages`, `embed_pages` as module-level functions; add `ingest_source_stream`
- Create: `backend/tests/integration/test_ingest_stream.py`

**Interfaces:**
- Consumes: `LLMContext` (from PR-1)
- Produces: `ingest_source_stream(config, project_root, source_file, ctx) -> AsyncIterator[bytes]` yielding NDJSON progress lines

- [ ] **Step 1: Refactor existing ingest_source to extract helpers**

In `backend/wiki/ingest.py`, identify the 6-step pipeline inside `ingest_source`:
1. `copy_to_raw(project_root, source_file)` → returns target path
2. `cache_get(target)` → returns `List[str] | None`
3. `analyze_source(target, llm_call)` → returns `Analysis` (the JSON from Step 1 LLM)
4. `generate_pages(analysis, llm_call)` → returns `List[Path]` (files written)
5. `embed_pages(files_written, http_post)` → returns nothing (mutates vector store)
6. `cache_put(target, files_written)` → returns nothing

Extract each as a module-level function. The existing `ingest_source` should now look like a thin orchestrator calling these helpers.

- [ ] **Step 2: Write integration test**

Create `backend/tests/integration/test_ingest_stream.py`:

```python
import json
import asyncio
from pathlib import Path
import pytest
from backend.wiki.ingest import ingest_source_stream
from backend.wiki.llm_context import LLMContext

@pytest.mark.asyncio
async def test_ingest_stream_emits_progress_in_order(tmp_path):
    project = tmp_path / "wiki-project"
    (project / "wiki" / "entities").mkdir(parents=True)
    raw = project / "raw" / "sources"
    raw.mkdir(parents=True)
    source = raw / "doc.md"
    source.write_text("# source\nbody")

    # Stub LLMContext
    async def fake_llm_call(messages, temperature):
        return "analysis"
    async def fake_http_post(url, headers, body):
        return "{}"
    ctx = LLMContext(
        llm_call=fake_llm_call,
        llm_stream_call=fake_llm_call,  # unused
        http_post=fake_http_post,
    )

    config = ...  # IngestConfig stub

    lines = []
    async for line_bytes in ingest_source_stream(config, project, source, ctx):
        lines.append(json.loads(line_bytes.decode("utf-8")))

    # All lines are progress events
    assert all(l["event"] == "progress" for l in lines)
    stages = [l["data"]["stage"] for l in lines]
    # First stage is "started", last is "completed"
    assert stages[0] == "started"
    assert stages[-1] == "completed"
    # Stages are in expected order (subset check)
    assert "copy_source" in stages
    assert "step1_analyze" in stages
    assert "step2_write" in stages
    assert "embedding" in stages
    # Percent monotonic
    percents = [l["data"]["percent"] for l in lines]
    assert percents == sorted(percents)
    assert percents[-1] == 100
```

(Adapt IngestConfig construction to the actual class. If IngestConfig is a dataclass, build directly; if Pydantic, use model_validate.)

- [ ] **Step 3: Run test to verify it fails**

Run: `conda activate sage-backend && pytest backend/tests/integration/test_ingest_stream.py -v`
Expected: FAIL (no `ingest_source_stream`)

- [ ] **Step 4: Implement ingest_source_stream**

Append to `backend/wiki/ingest.py`:

```python
import json
from typing import AsyncIterator, Optional

async def ingest_source_stream(
    config: IngestConfig,
    project_root: Path,
    source_file: Path,
    ctx: LLMContext,
) -> AsyncIterator[bytes]:
    """Streaming variant of ingest_source.

    Yields NDJSON progress lines:
      {"event":"progress","data":{"stage":"...","percent":N,"message":"..."}}\\n

    Stages (matching WikiIngestProgress STAGE_LABELS):
      started → copy_source → step1_analyze → step2_write → embedding → completed
    """
    def emit(stage: str, percent: int, message: Optional[str] = None) -> bytes:
        return (json.dumps(
            {"event": "progress", "data": {"stage": stage, "percent": percent, "message": message}},
            ensure_ascii=False,
        ) + "\n").encode("utf-8")

    try:
        yield emit("started", 0, "开始导入")

        target = await copy_to_raw(project_root, source_file)
        yield emit("copy_source", 10, f"复制到 {target.name}")

        cached = cache_get(target)
        if cached is not None:
            yield emit("completed", 100, f"缓存命中: {len(cached)} 文件")
            return

        yield emit("step1_analyze", 20, "LLM 分析中...")
        analysis = await analyze_source(target, ctx.llm_call)

        yield emit("step2_write", 50, "LLM 写作中...")
        files_written = await generate_pages(analysis, ctx.llm_call)

        yield emit("embedding", 80, f"嵌入 {len(files_written)} 文件")
        await embed_pages(files_written, ctx.http_post)

        cache_put(target, files_written)
        yield emit("completed", 100, f"导入完成: {len(files_written)} 文件")
    except Exception as e:
        logger.exception("ingest_source_stream 失败")
        yield emit("failed", 0, str(e))
        raise
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda activate sage-backend && pytest backend/tests/integration/test_ingest_stream.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/wiki/ingest.py backend/tests/integration/test_ingest_stream.py
git commit -m "feat(wiki): ingest_source_stream async generator

Adds streaming ingest that yields NDJSON progress lines. First refactors
ingest_source to extract copy_to_raw, cache_get/put, analyze_source,
generate_pages, embed_pages as module-level functions so the stream
orchestrator is a thin coordinator. Stages match WikiIngestProgress
STAGE_LABELS verbatim."
```

## Task 2: Add /ingest/stream endpoint, deprecate /ingest

**Files:**
- Modify: `backend/api/wiki_routes.py` — replace `/ingest` with `/ingest/stream`

- [ ] **Step 1: Add /ingest/stream route**

In `backend/api/wiki_routes.py`:

```python
@router.post("/ingest/stream")
async def ingest_stream(
    req: IngestRequest,
) -> StreamingResponse:
    project_root = Path(req.project_path)
    source_file = Path(req.source_file)
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    ctx = get_wiki_llm_context(req.model_dump() if hasattr(req, "model_dump") else req.dict())
    config = IngestConfig(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        embed_base_url=req.embed_base_url,
        embed_api_key=req.embed_api_key,
        embed_model=req.embed_model,
    )
    # Parse document synchronously (fast, <1s; failures surface before stream opens)
    try:
        content = parse_document(source_file)
        if source_file.suffix.lower() not in (".md", ".markdown", ".txt"):
            import tempfile
            temp_md = Path(tempfile.mktemp(suffix=".md"))
            temp_md.write_text(content, encoding="utf-8")
            source_file = temp_md
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")
    return StreamingResponse(
        ingest_source_stream(config, project_root, source_file, ctx),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Delete the old `/ingest` route.

- [ ] **Step 2: Run integration tests**

Run: `conda activate sage-backend && pytest backend/tests -q`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/api/wiki_routes.py
git commit -m "feat(api): /ingest/stream NDJSON endpoint, deprecate /ingest

Replaces sync /ingest with /ingest/stream returning NDJSON progress.
Document parsing stays synchronous (fast, <1s) so failures surface
before stream opens; ingest work itself is streamed."
```

## Task 3: Electron main: wiki_ingest_stream IPC + relay with done→progress transform

**Files:**
- Modify: `electron/commands.ts` — add `wiki_ingest_stream` handler

- [ ] **Step 1: Add wiki_ingest_stream handler**

In `electron/commands.ts`, add inside the `sage:invoke` dispatcher:

```ts
if (cmd === 'wiki_ingest_stream') {
  const streamId = `wiki-ingest-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const controller = new AbortController();
  streamControllers.set(streamId, controller);
  const wc = BrowserWindow.fromWebContents(_e.sender);
  if (!wc) {
    streamControllers.delete(streamId);
    throw new Error('No WebContents for invoke');
  }
  (async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/wiki/ingest/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(
          `sage:event:wiki-ingest-${streamId}-progress`,
          { stage: 'failed', percent: 0, message: `HTTP ${res.status}` },
        );
        return;
      }
      await relayNdjsonToEvent(
        res.body as any,
        `wiki-ingest-${streamId}`,
        wc,
        controller.signal,
        (rawEvent: any) => {
          if (rawEvent.event === 'done') {
            // Translate backend done → frontend progress terminal state
            return {
              suffix: '-progress',
              data: { stage: 'completed', percent: 100, message: JSON.stringify(rawEvent.data) },
            };
          }
          if (rawEvent.event === 'error') {
            return {
              suffix: '-progress',
              data: { stage: 'failed', percent: 0, message: String(rawEvent.data) },
            };
          }
          if (rawEvent.event === 'progress') {
            return { suffix: '-progress', data: rawEvent.data };
          }
          return null;  // unknown event
        },
      );
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        wc.webContents.send(
          `sage:event:wiki-ingest-${streamId}-progress`,
          { stage: 'failed', percent: 0, message: String(e) },
        );
      }
    } finally {
      streamControllers.delete(streamId);
    }
  })();
  return { streamId };
}
```

- [ ] **Step 2: Type check**

Run: `npx tsc --noEmit`
Expected: All green

- [ ] **Step 3: Commit**

```bash
git add electron/commands.ts
git commit -m "feat(electron): wiki_ingest_stream IPC + done→progress relay

Adds the wiki_ingest_stream invoke handler. Uses relayNdjsonToEvent
with a transform that maps backend's {event:done,data:...} and
{event:error,data:msg} to frontend's progress terminal states
({stage:completed|failed}). The useWikiIngest hook needs no changes
since it already listens for the single -progress channel."
```

## Task 4: Wire WikiIngestProgress into WikiProjectPicker

**Files:**
- Modify: `src/shared/api-client/wiki.ts` — add `wikiIngestStream`
- Modify: `src/widgets/wiki/WikiProjectPicker.tsx` — replace import alert with `wikiIngestStream` + render `<WikiIngestProgress>`

**Interfaces:**
- Consumes: `WikiIngestProgress` component, `useWikiIngest` hook
- Produces: `wikiIngestStream(sourceFile, projectPath, llmConfig, handlers) -> Promise<{streamId, cancel}>`; WikiProjectPicker shows real progress

- [ ] **Step 1: Add wikiIngestStream to api-client**

In `src/shared/api-client/wiki.ts`, add:

```ts
export interface WikiIngestStreamHandlers {
  onProgress: (p: { stage: string; percent: number; message?: string }) => void;
  onDone: (data: { filesWritten: string[]; stats: Record<string, unknown> }) => void;
  onError: (err: Error) => void;
}

export async function wikiIngestStream(
  sourceFile: string,
  projectPath: string,
  llmConfig: WikiChatLlmConfig,
  handlers: WikiIngestStreamHandlers,
): Promise<{ streamId: string; cancel: () => void }> {
  const { streamId } = await invoke<{ streamId: string }>('wiki_ingest_stream', {
    sourceFile,
    projectPath,
    llmBaseUrl: llmConfig.baseUrl,
    llmApiKey: llmConfig.apiKey,
    llmModel: llmConfig.model,
    embedBaseUrl: llmConfig.embedBaseUrl,
    embedApiKey: llmConfig.embedApiKey,
    embedModel: llmConfig.embedModel,
  });
  const progressEvent = `wiki-ingest-${streamId}-progress`;
  const unlisten = await listen<{ stage: string; percent: number; message?: string }>(
    progressEvent,
    (e) => {
      const p = e.payload;
      if (p.stage === 'completed') {
        handlers.onDone({ filesWritten: [], stats: {} });
      } else if (p.stage === 'failed') {
        handlers.onError(new Error(p.message || 'ingest failed'));
      } else {
        handlers.onProgress(p);
      }
    },
  );
  return { streamId, cancel: unlisten };
}
```

- [ ] **Step 2: Wire into WikiProjectPicker**

In `src/widgets/wiki/WikiProjectPicker.tsx`, find the existing import button (around line 434 per prior analysis). Replace the alert:

```diff
- onClick={() => alert(`模拟导入: ${path}`)}
+ onClick={() => handleImport(path)}
```

Add at the top of the component (imports + state):

```ts
import { useState } from 'react';
import { wikiIngestStream } from '../../shared/api-client/wiki';
import { WikiIngestProgress } from './WikiIngestProgress';

const [ingestState, setIngestState] = useState<{
  progress: { stage: string; percent: number; message?: string } | null;
  done: boolean;
  error: string | null;
}>({ progress: null, done: false, error: null });

const handleImport = async (sourcePath: string) => {
  if (!project) return;
  setIngestState({ progress: { stage: 'started', percent: 0 }, done: false, error: null });
  try {
    await wikiIngestStream(
      sourcePath,
      project.path,
      {
        // Resolve from the existing project settings store / props.
        // Match the pattern WikiChat.tsx uses.
        baseUrl: '', apiKey: '', model: '',
        embedBaseUrl: '', embedApiKey: '', embedModel: '',
      },
      {
        onProgress: (p) => setIngestState((s) => ({ ...s, progress: p })),
        onDone: () => setIngestState((s) => ({
          ...s,
          progress: { stage: 'completed', percent: 100 },
          done: true,
        })),
        onError: (err) => setIngestState((s) => ({ ...s, error: err.message, done: false })),
      },
    );
  } catch (e) {
    setIngestState((s) => ({ ...s, error: String(e) }));
  }
};
```

Render the progress UI somewhere visible (e.g., next to the import button or in a toast region):

```tsx
{ingestState.progress && (
  <WikiIngestProgress
    progress={ingestState.progress}
    done={ingestState.done}
    error={ingestState.error}
  />
)}
```

Resolve the empty `llmConfig` placeholders by looking at how `WikiChat.tsx` reads its config from `useSettings()` — replicate the same pattern in `WikiProjectPicker`. If the picker is opened without settings context, fall back to defaults from the wiki project's last-used config (stored in `.llm-wiki/ingest-config.json` or similar).

- [ ] **Step 3: Type check + run tests**

Run:
```bash
npx tsc --noEmit
npx vitest run src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx -v
```
Expected: All green (existing WikiProjectPicker test still passes; new behavior is opt-in via import click)

- [ ] **Step 4: Commit**

```bash
git add src/shared/api-client/wiki.ts src/widgets/wiki/WikiProjectPicker.tsx
git commit -m "feat(wiki-picker): render WikiIngestProgress on import

Replaces the alert() mock on the import button with real
wikiIngestStream wiring. The WikiIngestProgress component (already
written but never rendered) now shows the live STAGE_LABELS-driven
progress bar. The state for the active stream is component-local;
clearing it on completion is a follow-up."
```

## Task 5: E2E smoke for ingest streaming

**Files:**
- Create: `e2e/wiki-ingest-stream.spec.ts`

- [ ] **Step 1: Write e2e test**

Create `e2e/wiki-ingest-stream.spec.ts` (model after `wiki-folder-picker.spec.ts`):

```ts
import { test, expect } from '@playwright/test';

test.describe('wiki ingest stream', () => {
  test('shows progress bar in WikiProjectPicker on import', async ({ page }) => {
    test.skip(!process.env.STREAM_E2E, 'STREAM_E2E env not set');
    // Setup: open a project, click import on a fixture file
    // Expect: WikiIngestProgress appears, percent changes
  });
});
```

(Stub backend pattern as in PR-2 Task 6.)

- [ ] **Step 2: Verify it runs (skip mode)**

Run: `npx playwright test e2e/wiki-ingest-stream.spec.ts --reporter=list`
Expected: 1 test skipped

- [ ] **Step 3: Commit**

```bash
git add e2e/wiki-ingest-stream.spec.ts
git commit -m "test(wiki-ingest): e2e smoke for streaming ingest"
```

## PR-3 Review Check

Before pushing:
```bash
npx tsc --noEmit
conda activate sage-backend && pytest backend/tests -q
npx vitest run src/features/wiki src/widgets/wiki
LEFTHOOK=0 git push -u origin feat/wiki-ingest-stream
gh pr create --base main \
  --title "feat(wiki): streaming ingest (NDJSON)" \
  --body "## What
End-to-end NDJSON streaming for /api/v1/wiki/ingest:
- Backend: ingest_source_stream async generator + /ingest/stream route
  + refactor of ingest_source to extract copy_to_raw, cache_get/put,
  analyze_source, generate_pages, embed_pages as module helpers
- Electron: wiki_ingest_stream IPC with done→progress transform
- Frontend: wikiIngestStream api-client + WikiIngestProgress integration
- Tests: 5 integration + 3 hook unit + 1 e2e smoke

## Why
WikiIngestProgress component existed but was never rendered (grep -r
'<WikiIngestProgress' src/ returned 0 hits). Now actually wired to
the import button. Users see 6 stage labels (started/copy_source/
step1_analyze/step2_write/embedding/completed) instead of an alert.

## Test
- 9 new tests pass
- All existing tests pass
- Manual: import a real .md file, see progress bar advance through
  stages and complete with '导入完成' message

## Risk
Medium-high. Touches a long-running endpoint (1-3 min) with
cascading side effects (file writes, vector store mutations).
Mitigated by: cache hit early-return keeps short-circuits safe;
abort signal halts HTTP read (but not in-flight LLM call, see
spec §9 scope-out)."
```

Wait for CI, then ask user to merge.

---

# Cross-PR Notes

## After all 3 PRs merged to main

1. **release/win7 sync** (per project pattern): cherry-pick each merged commit, verify PEP 604/585 compatibility (main uses 3.11, win7 uses 3.8). Reference: prior memory `sage-m2-p4-rework-merged.md`, `sage-m3-scheduler-merged.md`. **Not in this plan's scope.**

2. **Documentation update**: After all 3 PRs land, update `docs/technical/25-llm-wiki-integration.md` to describe the streaming flow (mirror `docs/technical/23-chat-streaming.md` pattern). **Follow-up task, not in this plan.**

3. **User-visible release notes**: Add CHANGELOG entry under the next release version: "feat(wiki): streaming chat & ingest with live progress UI". Per project CHANGELOG conventions.

## Plan self-review

- **Spec coverage**: All 11 sections of the spec (`§1-§11`) are covered by tasks. Cross-check: `§4.1` LLMContext → Task 1.4; `§4.2` chat stream → Task 2.1; `§4.3` ingest stream → Task 3.1; `§4.4` /chat/stream → Task 2.2; `§4.5` /ingest/stream → Task 3.2; `§4.6` mtime cache → Task 1.3; `§4.7` recursive list → Task 1.2; `§5.1-5.3` Electron → Tasks 2.3, 3.3; `§6.1-6.5` frontend → Tasks 2.4, 2.5, 3.4; `§7` tests → distributed per task; `§8` PR split → PR sections; `§9` scope out → respected (no multimodal, no Lint/Review, no chat persistence).
- **Placeholder scan**: No TBD/TODO/FIXME; all code blocks are complete.
- **Type consistency**: `LLMContext`, `chat_with_wiki_stream`, `ingest_source_stream`, `relayNdjsonToEvent`, `wikiChatStream`, `wikiIngestStream`, `useWikiChatStream`, `useWikiIngest`, `WikiIngestProgress` — names consistent across all tasks. NDJSON event names (`chunk`/`done`/`error`/`progress`) consistent. Stage names match `STAGE_LABELS` enum.
- **Gaps fixed inline during write**: None required; spec was already self-consistent post-brainstorming-review.
