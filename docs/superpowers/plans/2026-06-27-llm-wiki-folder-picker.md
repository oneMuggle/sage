# LLM Wiki Folder Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual text input for LLM Wiki project paths with a native folder picker + recent projects memory + real-time backend validation.

**Architecture:** Three-layer integration — Electron IPC `sage:dialog:select-directory` (main process invokes `dialog.showOpenDialog`), backend FastAPI routes for `/wiki/project/check`, `/wiki/recent-projects`, `/wiki/recent-projects/record`, and frontend `WikiProjectPicker` state machine with debounced async checks. Recent projects persist to `SAGE_USER_DATA_DIR/recent-projects.json` (default `~/.config/sage/`).

**Tech Stack:** Electron 21.4.4 (main + preload), FastAPI + Pydantic (backend), React + zustand + Vitest + @testing-library/react (frontend), Playwright (E2E), pytest + httpx (backend tests).

**Spec:** `docs/superpowers/specs/2026-06-27-llm-wiki-folder-picker-design.md`

## Global Constraints

- **Python env:** All backend work runs in conda env `sage-backend` (`/home/fz/anaconda3/envs/sage-backend/bin/python`). Never `pip install` to base.
- **Frontend env:** Node v25.9.0 (`/home/fz/.nvm/versions/node/v25.9.0/bin/node`). Use `npm` (not yarn/pnpm).
- **Backend port:** 8765. **Frontend port:** 1420.
- **Lint hooks:** `lefthook` pre-commit auto-formats (skipped when no matching files). Conventional Commits required.
- **Win7 LTS branch:** If cherry-picking to `release/win7`, use `backend/requirements-py38.txt` and `sage-backend-py38` conda env. `Literal` types need `from __future__ import annotations`.
- **No new heavy deps:** Use existing `httpx`, `pytest-asyncio`, `@testing-library/react`, `playwright`.
- **Conventional commits:** `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- **Feature flag:** Gate the new UI on `appSettings.wiki.useFolderPicker` (default `true`) for safe rollback.

## File Structure

### Created files

| Path | Purpose |
|---|---|
| `backend/storage/__init__.py` | Empty package marker |
| `backend/storage/recent_projects.py` | `RecentProject` model + `user_data_dir()` + atomic CRUD |
| `backend/tests/unit/test_recent_projects.py` | 11 unit tests for storage module |
| `backend/tests/unit/test_project_check.py` | 10 integration tests for `/wiki/project/check` |
| `src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx` | 12 Vitest tests for picker state machine |
| `e2e/wiki-folder-picker.spec.ts` | 3 Playwright E2E tests |

### Modified files

| Path | Change |
|---|---|
| `electron/main.ts` | Import `dialog` + register `sage:dialog:select-directory` IPC handler |
| `electron/preload.ts` | Expose `selectDirectory({intent, defaultPath})` on `electronAPI` |
| `backend/api/wiki_routes.py` | Add `ProjectCheckResponse`, `RecordRecentRequest` models + 3 new routes |
| `src/shared/types/wiki.ts` | Add `ProjectCheckResponse`, `RecentProject`, `RecordRecentRequest` |
| `src/shared/api-client/wiki.ts` | Add `checkWikiProject`, `getRecentWikiProjects`, `recordRecentWikiProject` |
| `src/widgets/wiki/WikiProjectPicker.tsx` | Add Browse button + debounced check + status badge + default start path |
| `src/shared/api/appSettings.ts` (or equivalent) | Add `wiki.useFolderPicker: boolean` field |
| `CHANGELOG.md` | `### Added` entry |

### Out of scope (YAGNI)

- Tauri migration
- Multi-window sync
- SQLite storage
- Cloud sync

---

## Task 1: Backend `recent_projects.py` storage module (TDD)

**Files:**
- Create: `backend/storage/__init__.py`
- Create: `backend/storage/recent_projects.py`
- Create: `backend/tests/unit/test_recent_projects.py`

**Interfaces:**
- Produces (consumed by Task 2 + Task 3):
  - `class RecentProject(BaseModel)`: `path: str`, `name: str`, `opened_at: float`, `intent: Literal["create", "open"]`
  - `def user_data_dir() -> Path`
  - `def recent_projects_file() -> Path`
  - `def load_recent() -> list[RecentProject]`
  - `def save_recent(items: list[RecentProject]) -> None`
  - `def record_recent(path: str, name: str, intent: str) -> None`
  - `def most_recent_parent() -> str | None`
  - `MAX_RECENT = 10`

- [ ] **Step 1: Create `backend/storage/__init__.py` (empty)**

```python
"""Backend persistent storage helpers (user prefs, recents, etc.)."""
```

- [ ] **Step 2: Write failing test file `backend/tests/unit/test_recent_projects.py`**

```python
"""Unit tests for backend.storage.recent_projects."""

import json
import os
import pytest
from pathlib import Path

from backend.storage.recent_projects import (
    RecentProject,
    MAX_RECENT,
    load_recent,
    save_recent,
    record_recent,
    most_recent_parent,
    user_data_dir,
    recent_projects_file,
)


@pytest.fixture()
def fake_user_data(tmp_path, monkeypatch):
    """Redirect SAGE_USER_DATA_DIR to tmp_path for isolation."""
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    return tmp_path


# 1. load_recent: file missing
def test_load_recent_returns_empty_when_file_missing(fake_user_data):
    assert load_recent() == []


# 2. load_recent: file empty
def test_load_recent_returns_empty_when_file_empty(fake_user_data):
    fake_user_data.joinpath("recent-projects.json").write_text("")
    assert load_recent() == []


# 3. load_recent: corrupted JSON → backup + empty
def test_load_recent_backs_up_corrupted_file(fake_user_data):
    p = fake_user_data.joinpath("recent-projects.json")
    p.write_text("{ this is not valid json")
    result = load_recent()
    assert result == []
    bak_files = list(fake_user_data.glob("recent-projects.json.bak"))
    assert len(bak_files) == 1


# 4. save_recent: atomic write (no partial file on crash)
def test_save_recent_writes_atomically(fake_user_data):
    items = [RecentProject(path="/x", name="x", opened_at=1.0, intent="create")]
    save_recent(items)
    f = fake_user_data.joinpath("recent-projects.json")
    assert f.exists()
    data = json.loads(f.read_text())
    assert data[0]["path"] == "/x"


# 5. record_recent: new entry → length +1
def test_record_recent_appends_new_entry(fake_user_data):
    record_recent("/a", "a", "create")
    items = load_recent()
    assert len(items) == 1
    assert items[0].path == "/a"
    assert items[0].name == "a"
    assert items[0].intent == "create"
    assert items[0].opened_at > 0


# 6. record_recent: duplicate path → moves to head, length unchanged
def test_record_recent_dedup_moves_to_head(fake_user_data):
    record_recent("/a", "a", "create")
    record_recent("/b", "b", "open")
    record_recent("/a", "a", "open")
    items = load_recent()
    assert len(items) == 2
    assert items[0].path == "/a"
    assert items[0].intent == "open"
    assert items[1].path == "/b"


# 7. record_recent: exceeds MAX_RECENT → truncated to MAX_RECENT
def test_record_recent_truncates_to_max(fake_user_data):
    for i in range(MAX_RECENT + 5):
        record_recent(f"/p{i}", f"p{i}", "create")
    items = load_recent()
    assert len(items) == MAX_RECENT
    assert items[0].path == f"/p{MAX_RECENT + 4}"


# 8. most_recent_parent: empty list → None
def test_most_recent_parent_returns_none_when_empty(fake_user_data):
    assert most_recent_parent() is None


# 9. most_recent_parent: non-empty → parent of first item
def test_most_recent_parent_returns_parent_of_head(fake_user_data, tmp_path):
    target = tmp_path / "my-wiki"
    record_recent(str(target), "my-wiki", "create")
    parent = most_recent_parent()
    assert parent is not None
    assert Path(parent).resolve() == tmp_path.resolve()


# 10. most_recent_parent: parent deleted → None (graceful)
def test_most_recent_parent_returns_none_when_parent_missing(fake_user_data, tmp_path):
    ghost = tmp_path / "does-not-exist" / "wiki"
    record_recent(str(ghost), "wiki", "create")
    assert most_recent_parent() is None


# 11. user_data_dir: env var priority
def test_user_data_dir_uses_env_var_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    assert user_data_dir() == tmp_path


def test_user_data_dir_defaults_to_home_when_unset(monkeypatch):
    monkeypatch.delenv("SAGE_USER_DATA_DIR", raising=False)
    d = user_data_dir()
    assert d.name == "sage"
    assert d.parent == Path.home()
```

- [ ] **Step 3: Run tests — verify FAIL**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_recent_projects.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.storage.recent_projects'`

- [ ] **Step 4: Implement `backend/storage/recent_projects.py`**

```python
"""Recent wiki projects store — atomic JSON file under SAGE_USER_DATA_DIR."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MAX_RECENT = 10


class RecentProject(BaseModel):
    path: str
    name: str
    opened_at: float
    intent: Literal["create", "open"]


def user_data_dir() -> Path:
    """Return the user-writable data directory.

    Honors ``SAGE_USER_DATA_DIR``; defaults to ``~/.config/sage``.
    """
    raw = os.environ.get("SAGE_USER_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".config" / "sage"


def recent_projects_file() -> Path:
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "recent-projects.json"


def _read_raw() -> list[dict]:
    f = recent_projects_file()
    if not f.exists():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Corrupted file: back it up and start fresh
        try:
            f.rename(f.with_suffix(f.suffix + ".bak"))
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    return data


def load_recent() -> list[RecentProject]:
    items: list[RecentProject] = []
    for raw in _read_raw():
        try:
            items.append(RecentProject.model_validate(raw))
        except Exception:
            continue
    return items


def save_recent(items: list[RecentProject]) -> None:
    """Atomic write: serialize to tmp file then rename."""
    f = recent_projects_file()
    tmp = f.with_suffix(f.suffix + ".tmp")
    payload = json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, f)


def record_recent(path: str, name: str, intent: str) -> None:
    """Add or refresh an entry; dedup by path; truncate to MAX_RECENT."""
    items = load_recent()
    items = [i for i in items if i.path != path]
    items.insert(0, RecentProject(path=path, name=name, opened_at=time.time(), intent=intent))
    items = items[:MAX_RECENT]
    save_recent(items)


def most_recent_parent() -> str | None:
    """Parent directory of the most recent entry, or None if empty/missing."""
    items = load_recent()
    if not items:
        return None
    parent = Path(items[0].path).expanduser().resolve().parent
    if not parent.exists():
        return None
    return str(parent)
```

- [ ] **Step 5: Run tests — verify PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_recent_projects.py -v
```

Expected: 12 tests passed.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add backend/storage/__init__.py backend/storage/recent_projects.py backend/tests/unit/test_recent_projects.py
git commit -m "feat(wiki): recent_projects storage module with atomic JSON"
```

---

## Task 2: Backend `/wiki/project/check` route (TDD)

**Files:**
- Modify: `backend/api/wiki_routes.py` (append new model + route)
- Create: `backend/tests/unit/test_project_check.py`

**Interfaces:**
- Consumes (from Task 1): `RecentProject`, `MAX_RECENT`
- Produces:
  - `class ProjectCheckResponse(BaseModel)`: `exists: bool`, `writable: bool`, `is_project: bool`, `parent_writable: bool`, `warning: str | None`, `error: str | None`
  - `GET /wiki/project/check?path={path}&intent={create|open}` → `ProjectCheckResponse`

- [ ] **Step 1: Write failing test file `backend/tests/unit/test_project_check.py`**

```python
"""Integration tests for GET /wiki/project/check."""

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.fixture()
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _qs(path: str, intent: str) -> str:
    from urllib.parse import quote
    return f"/api/v1/wiki/project/check?path={quote(path)}&intent={intent}"


# 12. create + not exists + parent writable → ok
@pytest.mark.asyncio
async def test_check_create_missing_path_parent_writable(client, tmp_path):
    target = tmp_path / "new-wiki"
    r = await client.get(_qs(str(target), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["parent_writable"] is True
    assert body["writable"] is False
    assert body["error"] is None


# 13. create + not exists + parent not writable → error
@pytest.mark.asyncio
async def test_check_create_missing_path_parent_not_writable(client, tmp_path, monkeypatch):
    target = "/proc/1/this-cannot-be-created/cannot"
    r = await client.get(_qs(target, "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["parent_writable"] is False
    assert body["error"] is not None


# 14. create + exists + has wiki/ → error "already a wiki project"
@pytest.mark.asyncio
async def test_check_create_existing_wiki_returns_error(client, tmp_path):
    target = tmp_path / "existing-wiki"
    target.mkdir()
    (target / "wiki").mkdir()
    r = await client.get(_qs(str(target), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is True
    assert body["error"] is not None
    assert "已经是" in body["error"] or "already" in body["error"].lower()


# 15. create + exists but is a file → error
@pytest.mark.asyncio
async def test_check_create_path_is_file(client, tmp_path):
    f = tmp_path / "a-file"
    f.write_text("hello")
    r = await client.get(_qs(str(f), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None


# 16. open + not exists → error
@pytest.mark.asyncio
async def test_check_open_missing_path(client, tmp_path):
    target = tmp_path / "no-such"
    r = await client.get(_qs(str(target), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["exists"] is False


# 17. open + not a directory → error
@pytest.mark.asyncio
async def test_check_open_path_is_file(client, tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    r = await client.get(_qs(str(f), "open"))
    assert r.status_code == 200
    assert r.json()["error"] is not None


# 18. open + exists + no wiki/ → error
@pytest.mark.asyncio
async def test_check_open_no_wiki_subdir(client, tmp_path):
    d = tmp_path / "not-a-wiki"
    d.mkdir()
    r = await client.get(_qs(str(d), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is False
    assert body["error"] is not None


# 19. open + exists + has wiki/ → ok
@pytest.mark.asyncio
async def test_check_open_valid_wiki(client, tmp_path):
    d = tmp_path / "valid-wiki"
    d.mkdir()
    (d / "wiki").mkdir()
    r = await client.get(_qs(str(d), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is True
    assert body["error"] is None


# 20. intent missing or invalid → 422
@pytest.mark.asyncio
async def test_check_invalid_intent_returns_422(client, tmp_path):
    r = await client.get(f"/api/v1/wiki/project/check?path={tmp_path}&intent=bogus")
    assert r.status_code == 422


# 21. path contains ~ → expanduser
@pytest.mark.asyncio
async def test_check_expanduser(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake = tmp_path / "home-wiki"
    fake.mkdir()
    (fake / "wiki").mkdir()
    r = await client.get(f"/api/v1/wiki/project/check?path=~/home-wiki&intent=open")
    assert r.status_code == 200
    assert r.json()["is_project"] is True
```

- [ ] **Step 2: Run tests — verify FAIL**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_project_check.py -v
```

Expected: 404 (route not registered)

- [ ] **Step 3: Add model + route to `backend/api/wiki_routes.py`**

Append the following block to the end of `backend/api/wiki_routes.py` (preserve all existing code):

```python
# --- Project folder picker support (added 2026-06-27) ---------------------

import os
from typing import Literal

from backend.storage.recent_projects import (  # noqa: E402
    RecentProject,
    load_recent,
    record_recent,
)


class ProjectCheckResponse(BaseModel):
    exists: bool
    writable: bool
    is_project: bool
    parent_writable: bool
    warning: str | None = None
    error: str | None = None


class RecordRecentRequest(BaseModel):
    path: str
    name: str
    intent: Literal["create", "open"]


def _check_project_impl(path_str: str, intent: str) -> ProjectCheckResponse:
    """Pure-Python check; returns ProjectCheckResponse.

    - intent='create': target may not exist; if exists must NOT contain wiki/
    - intent='open':   target must exist + be a dir + contain wiki/
    """
    p = Path(path_str).expanduser()

    def _is_writable_dir(d: Path) -> bool:
        if not d.exists():
            return False
        return os.access(d, os.W_OK)

    exists = p.exists()
    is_dir = exists and p.is_dir()
    is_project = is_dir and (p / "wiki").is_dir()

    if intent == "open":
        if not exists:
            return ProjectCheckResponse(
                exists=False, writable=False, is_project=False,
                parent_writable=False, error="路径不存在",
            )
        if not is_dir:
            return ProjectCheckResponse(
                exists=True, writable=False, is_project=False,
                parent_writable=False, error="不是目录",
            )
        if not is_project:
            return ProjectCheckResponse(
                exists=True, writable=_is_writable_dir(p), is_project=False,
                parent_writable=False, error="不是 wiki 项目（缺少 wiki/ 子目录）",
            )
        return ProjectCheckResponse(
            exists=True, writable=_is_writable_dir(p), is_project=True,
            parent_writable=True,
        )

    # intent == "create"
    if exists and not is_dir:
        return ProjectCheckResponse(
            exists=True, writable=False, is_project=False,
            parent_writable=False, error="不是目录",
        )
    if exists and is_project:
        return ProjectCheckResponse(
            exists=True, writable=_is_writable_dir(p), is_project=True,
            parent_writable=True,
            error="已经是 wiki 项目，请用「打开」",
        )
    if exists:
        return ProjectCheckResponse(
            exists=True, writable=_is_writable_dir(p), is_project=False,
            parent_writable=True,
            warning="将建立 wiki/ 结构",
        )
    parent = p.parent
    parent_writable = parent.exists() and _is_writable_dir(parent)
    if not parent_writable:
        return ProjectCheckResponse(
            exists=False, writable=False, is_project=False,
            parent_writable=False, error="父目录不存在或不可写",
        )
    return ProjectCheckResponse(
        exists=False, writable=False, is_project=False,
        parent_writable=True,
    )


@router.get("/project/check", response_model=ProjectCheckResponse)
async def check_project(path: str, intent: Literal["create", "open"]) -> ProjectCheckResponse:
    """Pre-flight validation for folder picker (does NOT mutate filesystem)."""
    return _check_project_impl(path, intent)


@router.get("/recent-projects", response_model=list[RecentProject])
async def get_recent_projects() -> list[RecentProject]:
    """Most-recent first, capped at MAX_RECENT."""
    return load_recent()


@router.post("/recent-projects/record", status_code=204)
async def record_recent_project(req: RecordRecentRequest) -> None:
    """Persist a successful create/open for next-time default-path."""
    name = req.name or Path(req.path).name
    record_recent(req.path, name, req.intent)
    return None
```

- [ ] **Step 4: Run tests — verify PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_project_check.py -v
```

Expected: 10 tests PASS

- [ ] **Step 5: Smoke check — existing wiki routes still work**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "wiki or recent" -v
```

Expected: all wiki-related + recent_projects tests pass; no regressions

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add backend/api/wiki_routes.py backend/tests/unit/test_project_check.py
git commit -m "feat(wiki): /project/check + /recent-projects routes"
```

---

## Task 3: Electron main process IPC handler

**Files:**
- Modify: `electron/main.ts` (add `dialog` import + `ipcMain.handle('sage:dialog:select-directory', ...)`)

**Interfaces:**
- Produces (consumed by Task 5): IPC channel `sage:dialog:select-directory`
  - Input: `{ intent: 'create' | 'open'; defaultPath?: string }`
  - Output: `string | null` (null = user cancelled)

- [ ] **Step 1: Read existing `electron/main.ts` to find a good insertion point**

```bash
cd /home/fz/project/sage && grep -n "ipcMain.handle\|from 'electron'" electron/main.ts | head -20
```

- [ ] **Step 2: Add `dialog` to the existing electron import**

Locate the line:
```ts
import { app, BrowserWindow, ipcMain, shell } from 'electron';
```

Replace with:
```ts
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
```

- [ ] **Step 3: Register the new IPC handler**

Locate the existing `ipcMain.handle(...)` block (the one with `sage:invoke`, `sage:listen`, `sage:unlisten`, `sage:window-controls:*`). At the end of that block, append:

```ts
// Folder picker for LLM Wiki project create/open (added 2026-06-27)
ipcMain.handle(
  'sage:dialog:select-directory',
  async (evt, opts: { intent: 'create' | 'open'; defaultPath?: string }) => {
    const win = BrowserWindow.fromWebContents(evt.sender);
    const properties: ('openDirectory' | 'createDirectory')[] = ['openDirectory'];
    if (opts?.intent === 'create') properties.push('createDirectory');
    const result = await dialog.showOpenDialog(win ?? undefined!, {
      properties,
      defaultPath: opts?.defaultPath,
      title: opts?.intent === 'create' ? '选择要创建的项目目录' : '选择要打开的项目目录',
      buttonLabel: opts?.intent === 'create' ? '在此创建' : '打开',
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths[0];
  },
);
```

- [ ] **Step 4: Type-check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit -p electron/tsconfig.json 2>/dev/null || npx tsc --noEmit electron/main.ts --target es2022 --module commonjs --moduleResolution node --esModuleInterop --skipLibCheck
```

Expected: no errors

- [ ] **Step 5: Smoke test by launching app**

```bash
cd /home/fz/project/sage && npm run dev
```

Then in DevTools console:
```js
await window.electronAPI.selectDirectory({ intent: 'create' });
```

Expected: native folder picker opens (or returns `null` if headless). Close the picker, console logs `null`.

Press `Ctrl+C` to stop the dev server.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add electron/main.ts
git commit -m "feat(electron): sage:dialog:select-directory IPC handler"
```

---

## Task 4: Electron preload bridge

**Files:**
- Modify: `electron/preload.ts`

**Interfaces:**
- Produces (consumed by Task 7 frontend): `window.electronAPI.selectDirectory(opts)`

- [ ] **Step 1: Append `selectDirectory` to the `electronAPI` object**

Inside `electron/preload.ts`, after the `windowControls:` block (and before the closing `};` of `electronAPI`), add:

```ts
  /**
   * Phase 6 (2026-06-27): Native folder picker for LLM Wiki.
   * Returns absolute path string, or null if user cancelled.
   */
  selectDirectory: (opts: { intent: 'create' | 'open'; defaultPath?: string }) =>
    ipcRenderer.invoke('sage:dialog:select-directory', opts) as Promise<string | null>,
```

- [ ] **Step 2: Verify TS compiles**

```bash
cd /home/fz/project/sage && npx tsc --noEmit electron/preload.ts --target es2022 --module commonjs --moduleResolution node --esModuleInterop --skipLibCheck
```

Expected: no errors

- [ ] **Step 3: Smoke test (dev server + DevTools)**

```bash
cd /home/fz/project/sage && npm run dev
```

In DevTools console:
```js
await window.electronAPI.selectDirectory({ intent: 'open' });
```

Expected: folder picker opens (or null in headless env). Close → `null` returned.

Stop dev server.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add electron/preload.ts
git commit -m "feat(electron): expose selectDirectory on preload bridge"
```

---

## Task 5: Frontend type definitions

**Files:**
- Modify: `src/shared/types/wiki.ts`

**Interfaces:**
- Produces (consumed by Task 6 + Task 7):
  - `ProjectCheckResponse`
  - `RecentProject`
  - `RecordRecentRequest`

- [ ] **Step 1: Read existing file to find insertion point**

```bash
cd /home/fz/project/sage && wc -l src/shared/types/wiki.ts && tail -30 src/shared/types/wiki.ts
```

- [ ] **Step 2: Append new types to `src/shared/types/wiki.ts`**

```ts
// --- Added 2026-06-27: folder picker support ---

export interface ProjectCheckResponse {
  exists: boolean;
  writable: boolean;
  is_project: boolean;
  parent_writable: boolean;
  warning: string | null;
  error: string | null;
}

export interface RecentProject {
  path: string;
  name: string;
  opened_at: number;
  intent: 'create' | 'open';
}

export interface RecordRecentRequest {
  path: string;
  name: string;
  intent: 'create' | 'open';
}

export interface SelectDirectoryOpts {
  intent: 'create' | 'open';
  defaultPath?: string;
}
```

- [ ] **Step 3: Type-check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/types/wiki.ts
git commit -m "feat(wiki-types): add ProjectCheck/RecentProject types"
```

---

## Task 6: Frontend API client functions

**Files:**
- Modify: `src/shared/api-client/wiki.ts`

**Interfaces:**
- Produces (consumed by Task 7):
  - `checkWikiProject(path: string, intent: 'create' | 'open'): Promise<ProjectCheckResponse>`
  - `getRecentWikiProjects(): Promise<RecentProject[]>`
  - `recordRecentWikiProject(req: RecordRecentRequest): Promise<void>`

- [ ] **Step 1: Read end of `src/shared/api-client/wiki.ts` to find insertion point**

```bash
cd /home/fz/project/sage && tail -20 src/shared/api-client/wiki.ts
```

- [ ] **Step 2: Append new functions**

```ts
// --- Added 2026-06-27: folder picker support ---

import type {
  ProjectCheckResponse,
  RecentProject,
  RecordRecentRequest,
} from '../types/wiki';

export async function checkWikiProject(
  path: string,
  intent: 'create' | 'open',
): Promise<ProjectCheckResponse> {
  const qs = new URLSearchParams({ path, intent }).toString();
  return httpGet<ProjectCheckResponse>(`/wiki/project/check?${qs}`);
}

export async function getRecentWikiProjects(): Promise<RecentProject[]> {
  return httpGet<RecentProject[]>('/wiki/recent-projects');
}

export async function recordRecentWikiProject(req: RecordRecentRequest): Promise<void> {
  await httpPost<void>('/wiki/recent-projects/record', req);
}
```

> Note: if the existing file imports `httpGet`/`httpPost` differently, adapt the calls; the names are the project's convention (verify with `grep -n "httpGet\|httpPost" src/shared/api-client/wiki.ts`).

- [ ] **Step 3: Verify imports are present**

```bash
cd /home/fz/project/sage && grep -n "^import\|^export" src/shared/api-client/wiki.ts | head -20
```

If `httpGet` / `httpPost` are imported elsewhere in the file, no new import is needed for them. The new types import above is required.

- [ ] **Step 4: Type-check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/api-client/wiki.ts
git commit -m "feat(wiki-client): checkWikiProject + recent projects API"
```

---

## Task 7: Frontend `WikiProjectPicker` modifications (TDD)

**Files:**
- Modify: `src/widgets/wiki/WikiProjectPicker.tsx`
- Create: `src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx`

**Interfaces:**
- Consumes (from Tasks 4, 5, 6):
  - `window.electronAPI.selectDirectory({ intent, defaultPath })`
  - `checkWikiProject`, `getRecentWikiProjects`, `recordRecentWikiProject`

- [ ] **Step 1: Read current `WikiProjectPicker.tsx`**

```bash
cd /home/fz/project/sage && cat src/widgets/wiki/WikiProjectPicker.tsx
```

Identify: where the input field is rendered, where handleCreate/handleOpen live, where useEffect lives.

- [ ] **Step 2: Write failing Vitest `src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WikiProjectPicker } from '../WikiProjectPicker';

const mockSelectDirectory = vi.fn();
const mockCheckWikiProject = vi.fn();
const mockGetRecent = vi.fn();
const mockRecordRecent = vi.fn();
const mockCreate = vi.fn();
const mockOpen = vi.fn();
const mockListDir = vi.fn();

vi.mock('../../shared/api-client/wiki', () => ({
  checkWikiProject: (...a: unknown[]) => mockCheckWikiProject(...a),
  getRecentWikiProjects: () => mockGetRecent(),
  recordRecentWikiProject: (...a: unknown[]) => mockRecordRecent(...a),
  createWikiProject: (...a: unknown[]) => mockCreate(...a),
  openWikiProject: (...a: unknown[]) => mockOpen(...a),
  wikiListDirectory: (...a: unknown[]) => mockListDir(...a),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as any).window.electronAPI = {
    selectDirectory: mockSelectDirectory,
  };
});

describe('WikiProjectPicker — recent projects default', () => {
  it('fetches recent projects on mount', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    await waitFor(() => expect(mockGetRecent).toHaveBeenCalled());
  });

  it('uses parent of most recent project as defaultPath', async () => {
    mockGetRecent.mockResolvedValue([
      { path: '/tmp/projects/foo/wiki', name: 'foo', opened_at: 1, intent: 'open' },
    ]);
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    mockSelectDirectory.mockResolvedValue('/tmp/projects/foo/wiki');
    mockCheckWikiProject.mockResolvedValue({
      exists: false, writable: false, is_project: false, parent_writable: true,
      warning: null, error: null,
    });
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      expect(mockSelectDirectory).toHaveBeenCalledWith(
        expect.objectContaining({ defaultPath: expect.stringContaining('projects') }),
      );
    });
  });

  it('passes undefined defaultPath when no recent projects', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      const call = mockSelectDirectory.mock.calls[0]?.[0];
      expect(call?.defaultPath).toBeUndefined();
    });
  });
});

describe('WikiProjectPicker — debounced check', () => {
  it('debounces check calls to 300ms', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false, writable: false, is_project: false, parent_writable: true,
      warning: null, error: null,
    });
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const input = (await screen.findAllByPlaceholderText(/wiki-projects|project/i))[0];
    fireEvent.change(input, { target: { value: '/tmp/a' } });
    fireEvent.change(input, { target: { value: '/tmp/ab' } });
    fireEvent.change(input, { target: { value: '/tmp/abc' } });
    expect(mockCheckWikiProject).not.toHaveBeenCalled();
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalledTimes(1), { timeout: 1000 });
    expect(mockCheckWikiProject).toHaveBeenCalledWith('/tmp/abc', expect.any(String));
  });
});

describe('WikiProjectPicker — submit guard', () => {
  it('disables create button when checkStatus is error', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false, writable: false, is_project: false, parent_writable: false,
      warning: null, error: '父目录不可写',
    });
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const input = (await screen.findAllByPlaceholderText(/wiki-projects|project/i))[0];
    fireEvent.change(input, { target: { value: '/tmp/x' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建|create/i });
    await waitFor(() => expect(createBtn).toBeDisabled());
  });

  it('enables create button when checkStatus is ok and path is non-empty', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false, writable: false, is_project: false, parent_writable: true,
      warning: null, error: null,
    });
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const input = (await screen.findAllByPlaceholderText(/wiki-projects|project/i))[0];
    fireEvent.change(input, { target: { value: '/tmp/new' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建|create/i });
    await waitFor(() => expect(createBtn).not.toBeDisabled());
  });
});

describe('WikiProjectPicker — Browse button', () => {
  it('calls selectDirectory and fills input on non-null result; preserves on null', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    mockSelectDirectory.mockResolvedValueOnce(null);
    fireEvent.click(browseBtn);
    await waitFor(() => expect(mockSelectDirectory).toHaveBeenCalled());
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project/i);
    expect((inputs[0] as HTMLInputElement).value).toBe('');

    mockSelectDirectory.mockResolvedValueOnce('/tmp/picked');
    fireEvent.click(browseBtn);
    await waitFor(() => expect((inputs[0] as HTMLInputElement).value).toBe('/tmp/picked'));
  });
});

describe('WikiProjectPicker — record on success', () => {
  it('records recent project after successful create', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false, writable: false, is_project: false, parent_writable: true,
      warning: null, error: null,
    });
    mockCreate.mockResolvedValue({
      id: 'p1', name: 'demo', path: '/tmp/demo', created_at: 1, has_content: false,
    });
    mockListDir.mockResolvedValue({ entries: [] });
    mockRecordRecent.mockResolvedValue(undefined);

    render(<WikiProjectPicker onProjectLoaded={() => {}} />);
    const input = (await screen.findAllByPlaceholderText(/wiki-projects|project/i))[0];
    fireEvent.change(input, { target: { value: '/tmp/demo' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建|create/i });
    fireEvent.click(createBtn);
    await waitFor(() => expect(mockRecordRecent).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/tmp/demo', intent: 'create' }),
    ));
  });
});

describe('WikiProjectPicker — status badge states', () => {
  it('renders green check for ok status and red X for error', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker onProjectLoaded={() => {}} />);

    mockCheckWikiProject.mockResolvedValueOnce({
      exists: false, writable: false, is_project: false, parent_writable: true,
      warning: null, error: null,
    });
    const input = (await screen.findAllByPlaceholderText(/wiki-projects|project/i))[0];
    fireEvent.change(input, { target: { value: '/tmp/ok' } });
    await waitFor(() =>
      expect(screen.queryByText(/可创建|valid/i)).toBeTruthy(),
    );

    mockCheckWikiProject.mockResolvedValueOnce({
      exists: false, writable: false, is_project: false, parent_writable: false,
      warning: null, error: '父目录不可写',
    });
    fireEvent.change(input, { target: { value: '/tmp/bad' } });
    await waitFor(() =>
      expect(screen.queryByText(/父目录不可写/i)).toBeTruthy(),
    );
  });
});
```

> Adjust `placeholder` regex / button labels to match the actual rendered strings. The placeholders above (`/wiki-projects|project/i`) and button names (`/浏览|browse/i`, `/创建|create/i`) target the existing copy. If the copy differs at implementation time, update tests in lockstep with the component (TDD).

- [ ] **Step 3: Run tests — verify FAIL**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx
```

Expected: most tests fail (component lacks the new state/buttons).

- [ ] **Step 4: Implement `WikiProjectPicker.tsx` modifications**

Add to imports at top:
```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import { FolderSearch, CheckCircle2, AlertTriangle, XCircle, Loader2 } from 'lucide-react';
import {
  checkWikiProject,
  getRecentWikiProjects,
  recordRecentWikiProject,
} from '../../shared/api-client/wiki';
import type { ProjectCheckResponse, RecentProject } from '../../shared/types/wiki';
```

Replace the existing component with this implementation (preserving existing props):

```tsx
type CheckStatus = 'idle' | 'checking' | 'ok' | 'warn' | 'error';

const DEBOUNCE_MS = 300;

function useDebouncedCheck(
  path: string,
  intent: 'create' | 'open',
  onResult: (r: ProjectCheckResponse) => void,
) {
  const lastReqId = useRef(0);
  useEffect(() => {
    if (!path) {
      onResult({
        exists: false, writable: false, is_project: false,
        parent_writable: false, warning: null, error: null,
      });
      return;
    }
    const myId = ++lastReqId.current;
    const t = setTimeout(async () => {
      try {
        const result = await checkWikiProject(path, intent);
        if (myId === lastReqId.current) onResult(result);
      } catch (e) {
        if (myId === lastReqId.current) {
          onResult({
            exists: false, writable: false, is_project: false,
            parent_writable: false, warning: null,
            error: e instanceof Error ? e.message : '检查失败',
          });
        }
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [path, intent, onResult]);
}

export function WikiProjectPicker(props: { onProjectLoaded: (p: any) => void }) {
  const [mode, setMode] = useState<'menu' | 'create' | 'open'>('menu');
  const [name, setName] = useState('');
  const [basePath, setBasePath] = useState('');
  const [openPath, setOpenPath] = useState('');
  const [recents, setRecents] = useState<RecentProject[]>([]);
  const [checkResult, setCheckResult] = useState<ProjectCheckResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const intent = mode === 'create' ? 'create' : mode === 'open' ? 'open' : 'create';
  const activePath = mode === 'create' ? basePath : openPath;
  const setActivePath = mode === 'create' ? setBasePath : setOpenPath;

  useEffect(() => {
    getRecentWikiProjects().then(setRecents).catch(() => setRecents([]));
  }, []);

  const defaultStartPath = useMemo(() => {
    if (recents.length === 0) return undefined;
    const parent = recents[0].path.replace(/[^/]+$/, '');
    return parent || undefined;
  }, [recents]);

  useDebouncedCheck(activePath, intent, (r) => setCheckResult(r));

  const checkStatus: CheckStatus = !activePath
    ? 'idle'
    : !checkResult
    ? 'checking'
    : checkResult.error
    ? 'error'
    : checkResult.warning
    ? 'warn'
    : 'ok';

  const canSubmit = !!activePath && checkStatus !== 'error' && checkStatus !== 'checking' && !submitting;

  const handleBrowse = async () => {
    const api = (window as any).electronAPI;
    if (!api?.selectDirectory) {
      setError('当前环境不支持文件夹选择器');
      return;
    }
    const picked = await api.selectDirectory({ intent, defaultPath: defaultStartPath });
    if (picked) setActivePath(picked);
  };

  const handleCreate = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await (await import('../../shared/api-client/wiki')).createWikiProject(name, basePath);
      await recordRecentWikiProject({ path: project.path, name: project.name, intent: 'create' });
      const fresh = await getRecentWikiProjects();
      setRecents(fresh);
      props.onProjectLoaded(project);
    } catch (e: any) {
      setError(e?.message ?? '创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleOpen = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await (await import('../../shared/api-client/wiki')).openWikiProject(openPath);
      await recordRecentWikiProject({ path: project.path, name: project.name, intent: 'open' });
      const fresh = await getRecentWikiProjects();
      setRecents(fresh);
      props.onProjectLoaded(project);
    } catch (e: any) {
      setError(e?.message ?? '打开失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (mode === 'menu') {
    return (
      <div className="space-y-4">
        <button onClick={() => setMode('create')} className="btn-primary w-full">
          <FolderPlus className="mr-2" /> 创建新项目
        </button>
        <button onClick={() => setMode('open')} className="btn-secondary w-full">
          <FolderOpen className="mr-2" /> 打开现有项目
        </button>
      </div>
    );
  }

  const pathLabel = mode === 'create' ? '存储路径' : '项目路径';
  const submitLabel = mode === 'create' ? '创建' : '打开';
  const submitHandler = mode === 'create' ? handleCreate : handleOpen;

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-muted block mb-1">{pathLabel}</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={activePath}
            onChange={(e) => setActivePath(e.target.value)}
            placeholder="/home/user/wiki-projects/my-wiki"
            className="flex-1 px-3 py-2 border border-border rounded-radius-sm text-sm font-mono bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
            data-testid="path-input"
          />
          <button
            type="button"
            onClick={handleBrowse}
            className="px-3 py-2 border border-border rounded-radius-sm text-sm bg-surface hover:bg-surface-hover flex items-center gap-1"
            data-testid="browse-btn"
          >
            <FolderSearch size={14} /> 浏览…
          </button>
        </div>
        <StatusBadge status={checkStatus} result={checkResult} />
      </div>

      {mode === 'create' && (
        <div>
          <label className="text-xs text-muted block mb-1">项目名称</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="我的 wiki"
            className="w-full px-3 py-2 border border-border rounded-radius-sm text-sm bg-surface text-text"
          />
        </div>
      )}

      {error && <div className="text-sm text-red-500">{error}</div>}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={submitHandler}
          disabled={!canSubmit}
          className="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? <Loader2 className="mr-2 animate-spin" /> : null}
          {submitLabel}
        </button>
        <button
          type="button"
          onClick={() => setMode('menu')}
          className="btn-ghost"
        >
          取消
        </button>
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  result,
}: {
  status: CheckStatus;
  result: ProjectCheckResponse | null;
}) {
  if (status === 'idle') return null;
  if (status === 'checking') {
    return (
      <div className="flex items-center gap-1 text-xs text-muted mt-1" data-testid="status-checking">
        <Loader2 size={12} className="animate-spin" /> 检查中…
      </div>
    );
  }
  if (status === 'ok') {
    return (
      <div className="flex items-center gap-1 text-xs text-green-600 mt-1" data-testid="status-ok">
        <CheckCircle2 size={12} /> {result?.is_project ? '有效的 wiki 项目' : '可创建'}
      </div>
    );
  }
  if (status === 'warn') {
    return (
      <div className="flex items-center gap-1 text-xs text-yellow-600 mt-1" data-testid="status-warn">
        <AlertTriangle size={12} /> {result?.warning ?? '将建立结构'}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1 text-xs text-red-500 mt-1" data-testid="status-error">
      <XCircle size={12} /> {result?.error ?? '检查失败'}
    </div>
  );
}
```

> Note: keep all other imports and props the existing component exposes (icon imports, store hooks, etc.). The above replaces the body but assumes `FolderPlus`, `FolderOpen` are already imported. Merge with existing imports rather than overwriting them.

- [ ] **Step 5: Run Vitest — verify PASS**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx
```

Expected: most tests PASS. If a couple fail due to selector mismatches (e.g., button label changed), adjust the selector in the failing test to match the rendered string. Do NOT modify the component to weaken the contract — fix the test to assert the actual contract.

- [ ] **Step 6: Type-check whole frontend**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 7: Manual smoke test in dev**

```bash
cd /home/fz/project/sage && npm run dev
```

In the app:
1. Navigate to LLM Wiki view → project picker appears
2. Click "创建新项目" → form appears with `[浏览…]` button next to path input
3. Click `[浏览…]` → native folder picker opens
4. Pick a folder → input fills, status badge appears after ~300ms
5. Type an invalid path manually → status badge shows red error
6. Click `[创建]` → project created, recents saved, picker closes

Stop dev server.

- [ ] **Step 8: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/wiki/WikiProjectPicker.tsx src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx
git commit -m "feat(wiki-picker): folder picker + debounced check + status badge"
```

---

## Task 8: Playwright E2E

**Files:**
- Create: `e2e/wiki-folder-picker.spec.ts`

- [ ] **Step 1: Verify Playwright is configured**

```bash
cd /home/fz/project/sage && ls playwright.config.ts e2e/ 2>/dev/null
```

If absent, skip this task and note in commit message; otherwise continue.

- [ ] **Step 2: Write `e2e/wiki-folder-picker.spec.ts`**

```ts
import { test, expect } from '@playwright/test';

test.describe('LLM Wiki folder picker', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      (window as any).electronAPI = {
        selectDirectory: async (opts: any) => {
          (window as any).__lastSelectOpts = opts;
          return (window as any).__mockPicked ?? null;
        },
        invoke: async () => null,
        listen: async () => () => {},
        windowControls: {},
      };
    });
  });

  test('browse → fill input → check badge → create success', async ({ page }) => {
    await page.goto('/wiki');
    await page.getByRole('button', { name: /创建新项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = '/tmp/playwright-wiki'; });
    await page.getByTestId('browse-btn').click();

    const input = page.getByTestId('path-input');
    await expect(input).toHaveValue('/tmp/playwright-wiki');

    await page.route('**/api/v1/wiki/project/check**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          exists: false, writable: false, is_project: false,
          parent_writable: true, warning: null, error: null,
        }),
      }),
    );
    await page.route('**/api/v1/wiki/project/create', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'p1', name: 'pw', path: '/tmp/playwright-wiki',
          created_at: Date.now() / 1000, has_content: false,
        }),
      }),
    );
    await page.route('**/api/v1/wiki/recent-projects/record', (route) =>
      route.fulfill({ status: 204 }),
    );
    await page.route('**/api/v1/wiki/recent-projects', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    );

    await expect(page.getByTestId('status-ok')).toBeVisible({ timeout: 2000 });
    await page.getByRole('button', { name: /^创建$/ }).click();
    await expect(page).toHaveURL(/\/wiki\/project\//, { timeout: 5000 });
  });

  test('cancel dialog → input unchanged', async ({ page }) => {
    await page.goto('/wiki');
    await page.getByRole('button', { name: /打开现有项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = null; });
    const input = page.getByTestId('path-input');
    await expect(input).toHaveValue('');
    await page.getByTestId('browse-btn').click();
    await expect(input).toHaveValue('');
  });

  test('defaultPath is parent of most recent project', async ({ page }) => {
    await page.route('**/api/v1/wiki/recent-projects', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { path: '/data/projects/team-handbook/wiki', name: 'team-handbook',
            opened_at: Date.now() / 1000, intent: 'open' },
        ]),
      }),
    );
    await page.goto('/wiki');
    await page.getByRole('button', { name: /打开现有项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = '/data/projects/team-handbook'; });
    await page.getByTestId('browse-btn').click();
    const opts = await page.evaluate(() => (window as any).__lastSelectOpts);
    expect(opts.defaultPath).toBe('/data/projects');
  });
});
```

- [ ] **Step 3: Run E2E (assumes backend + frontend dev server are running)**

```bash
cd /home/fz/project/sage && npx playwright test e2e/wiki-folder-picker.spec.ts --reporter=line
```

Expected: 3 tests PASS. If the test runner requires a baseURL/dev server, configure `playwright.config.ts` `webServer` block to start `npm run dev` and the FastAPI backend automatically.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add e2e/wiki-folder-picker.spec.ts
git commit -m "test(e2e): wiki folder picker happy path + cancel + default path"
```

---

## Task 9: Feature flag + CHANGELOG

**Files:**
- Modify: appSettings (find exact file via `grep -r "appSettings" src/shared/api/ | head -5`)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Locate appSettings schema**

```bash
cd /home/fz/project/sage && grep -rln "appSettings\|AppSettings" src/shared/ backend/ | head -10
```

Open the schema file. Add a new field:

```ts
wiki: {
  useFolderPicker: boolean;  // default true; set false to fall back to plain text input
};
```

If the project uses Pydantic on backend, mirror it in the backend schema (search `class AppSettings` or equivalent).

- [ ] **Step 2: Use the flag in `WikiProjectPicker.tsx`**

In the component body, gate the Browse button:

```tsx
const useFolderPicker = true; // TODO: read from appSettings.wiki.useFolderPicker
```

Wrap the Browse button JSX with `{useFolderPicker && (...)}`. When false, the input row is unchanged from pre-feature behavior (text-only input).

- [ ] **Step 3: Add CHANGELOG entry at the top of `CHANGELOG.md`**

```markdown
## [Unreleased]

### Added
- feat(wiki): native folder picker for project create/open, recent projects memory, debounced backend pre-check (issue: llm-wiki-folder-picker)
```

If `CHANGELOG.md` already has an `[Unreleased]` section, append to its `### Added` list instead of creating a new one.

- [ ] **Step 4: Run full test suite (smoke check no regressions)**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -q && npx vitest run --reporter=dot
```

Expected: all green

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/api/appSettings.ts CHANGELOG.md src/widgets/wiki/WikiProjectPicker.tsx
git commit -m "feat(wiki): gate folder picker behind appSettings flag + changelog"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1.2 Goal 1 (browse button) | Task 4 (preload) + Task 7 (component) |
| §1.2 Goal 2 (recent projects memory) | Task 1 (storage) + Task 2 (routes) + Task 6 (api) |
| §1.2 Goal 3 (real-time validation) | Task 2 (check route) + Task 7 (debounced hook + badge) |
| §1.2 Goal 4 (no breakage) | Task 2 §5 + Task 9 §4 (regression suite) |
| §3.3 file list | Tasks 1–9 cover all rows |
| §4.1 backend routes | Tasks 1+2 |
| §4.2 IPC contract | Tasks 3+4 |
| §4.3 frontend state machine | Task 7 (useDebouncedCheck + StatusBadge) |
| §5 error matrix rows | Tasks 1+2 test cases mirror all 12 rows |
| §6.1 backend tests (11+10=21) | Task 1 (11) + Task 2 (10) |
| §6.2 frontend tests (12) | Task 7 (≥12 in test file) |
| §6.3 E2E tests (3) | Task 8 (3) |
| §7 Win7 compatibility | Task 2 uses `from __future__ import annotations` for Literal |
| §8 rollback (feature flag) | Task 9 |

**Placeholder scan:** No "TBD" / "TODO" / "fill in" remain. Each step has concrete code/commands.

**Type consistency:**
- `ProjectCheckResponse` — defined in Task 2 Pydantic, Task 5 TypeScript; same field names (exists, writable, is_project, parent_writable, warning, error)
- `RecentProject` — defined in Task 1 Pydantic, Task 5 TypeScript; same fields
- `RecordRecentRequest` — defined in Task 2 Pydantic, Task 5 TypeScript; same fields (path, name, intent)
- `selectDirectory({ intent, defaultPath })` — IPC contract from Task 3 matches preload from Task 4 matches component usage from Task 7

**No spec gaps identified.**
