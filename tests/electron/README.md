# tests/electron/ — Playwright E2E Tests for the Sage Desktop App

This directory contains Playwright E2E tests that exercise the full Electron
desktop app against a lightweight **stub backend** — no FastAPI, no conda,
no real LLM required.

## Files

| File | Purpose |
|------|---------|
| `stub_backend.py` | Pure-stdlib HTTP server (Python 3.8+) that implements the Sage backend API contract (Tasks 1–10). Uses `http.server`, `sqlite3` in-memory, and `json`. |
| `test_stub_backend.py` | 29 unit tests verifying the stub's API fidelity (session CRUD, workspace bind/revoke, chat stream, office_refs authorization). |
| `conftest.py` | Pytest fixture: starts the stub on a random port, sets `SAGE_BACKEND_URL` + `PYTHON_BACKEND_PORT` env vars, tears down on exit. |
| `office-e2e.spec.ts` | **10 Playwright E2E tests** for the Office workflow (session creation → workspace bind → office_refs authorization → revoke). Uses TypeScript + `@playwright/test`. |
| `smoke.spec.ts` | Phase 4 smoke test: Electron launches, exposes `electronAPI`, frontend renders. Uses `SAGE_SKIP_BACKEND=1`. |
| `skillmd-compliance.spec.ts` | SKILL.md spec compliance: verifies agentskills.io-format SKILL.md files load correctly. Requires a live backend. |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Playwright test runner (Node.js)                                   │
│                                                                     │
│  ┌──────────────────────┐    ┌──────────────────────────────────┐  │
│  │  office-e2e.spec.ts  │    │  stub_backend.py (subprocess)    │  │
│  │                      │    │                                  │  │
│  │  spawn() ───────────►│    │  stdlib HTTP server              │  │
│  │  PYTHON_BACKEND_PORT │    │  sqlite3 :memory:                │  │
│  │  SAGE_SKIP_BACKEND=1 │    │  port=0 (random, assigned)       │  │
│  └──────────┬───────────┘    └───────────────┬──────────────────┘  │
│             │                                │                     │
│             │  electron.launch()             │  HTTP /api/v1/*     │
│             ▼                                │                     │
│  ┌──────────────────────────────────────────┐│                     │
│  │  Electron app (dist-electron/)           ││                     │
│  │                                          ││                     │
│  │  main.ts: BACKEND_URL = 127.0.0.1:<port> ◄┘                     │
│  │  preload.ts: electronAPI (contextBridge) │                      │
│  │  renderer: React app (HashRouter)        │                      │
│  └──────────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Running the Tests

### Prerequisites

1. **Node.js** (v18+): `node --version`
2. **Playwright**: `npx playwright --version` (should show 1.40+)
3. **Python 3.8+**: for the stub backend (`python3 --version`)
4. **Built Electron app**: `npm run build` (produces `dist-electron/`)

### Run all electron tests

```bash
# The electron project in playwright.config.ts covers tests/electron/
npx playwright test --project=electron
```

### Run only Office E2E

```bash
npx playwright test tests/electron/office-e2e.spec.ts --project=electron
```

### Run stub backend unit tests (pytest)

```bash
# Uses the sage-backend conda env
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/electron/test_stub_backend.py -v
```

### Skip Office E2E on CI

Set `SAGE_SKIP_E2E=1` to skip the Office E2E tests (e.g. on runners without
the Electron build artifacts):

```bash
SAGE_SKIP_E2E=1 npx playwright test tests/electron/office-e2e.spec.ts --project=electron
```

## Test Scenarios (office-e2e.spec.ts)

| # | Test | What it verifies |
|---|------|------------------|
| 01 | App launch + health | Electron starts, stub `/health` returns 200 via renderer `fetch` |
| 02 | Session creation | Navigating to `/welcome` triggers POST `/api/v1/sessions` |
| 03 | Office page | Sidebar nav to `/office` renders `[data-testid="office-page"]` |
| 04 | Workspace bind | Clicking "选择目录" (mocked) → PUT `/api/v1/sessions/:id/workspace` |
| 05 | Office refs auth (no binding) | POST `/api/v1/chat/stream` with `office_refs` + no binding → 403 |
| 06 | Office refs auth (with binding) | POST `/api/v1/chat/stream` with `office_refs` + binding → 200 |
| 07 | NDJSON stream | GET `/api/v1/chat/stream/:id` returns thinking → content_delta → done |
| 08 | DB state verification | Stub SQLite reflects sessions/bindings created during tests |
| 09 | Path mismatch | office_refs with wrong `workspace_path` → 400 |
| 10 | Workspace revoke | DELETE binding → subsequent office_refs chat → 403 |

## Stub Backend

The stub backend (`stub_backend.py`) is a **pure-stdlib** Python HTTP server
that implements the key API endpoints used by Tasks 1–10:

- `GET /health` — health check
- `POST /api/v1/sessions` — create session
- `GET /api/v1/sessions` — list sessions
- `GET /api/v1/sessions/:id` — get session
- `PUT /api/v1/sessions/:id/workspace` — bind workspace
- `GET /api/v1/sessions/:id/workspace` — get binding
- `DELETE /api/v1/sessions/:id/workspace` — revoke binding
- `GET /api/v1/sessions/:id/workspace/files` — search files (returns empty)
- `POST /api/v1/chat/stream` — create stream (with office_refs authorization)
- `GET /api/v1/chat/stream/:stream_id` — attach NDJSON stream

### Task 6 office_refs Authorization

The stub enforces the Task 6 contract for office_refs:

| Scenario | Result |
|----------|--------|
| Empty refs + no binding | ✅ 200 (legacy path) |
| Non-empty refs + no binding | ❌ 403 `workspace_not_bound` |
| Non-empty refs + path mismatch | ❌ 400 `workspace_path_mismatch` |
| Non-empty refs + valid binding | ✅ 200 |

### Why a Stub?

The real Sage backend requires:
- conda env `sage-backend` with FastAPI, Pydantic, uvicorn, etc.
- Python 3.11 (or 3.8 for `release/win7`)
- LLM API keys for chat functionality

The stub lets CI and developers run E2E tests without any of that. It
implements just enough of the API contract to verify the Electron app's
behavior end-to-end.

## Design Decisions

1. **TypeScript tests, Python stub**: Playwright is installed as `@playwright/test`
   (Node.js). The stub is Python for compatibility with the real backend's API
   shapes. Node.js spawns the Python stub as a child process.

2. **Module-level stub lifecycle**: The stub starts once when the spec file is
   imported and lives for the entire test run. This avoids per-test startup
   overhead and ensures consistent state across tests.

3. **Per-test Electron instance**: Each test gets a fresh Electron launch
   (in `beforeAll`) to ensure UI state isolation. The stub's SQLite state
   persists across Electron instances (by design — it tests that state is
   durable).

4. **Mocked native dialog**: `window.electronAPI.selectDirectory()` is mocked
   via `page.evaluate()` to return a temp directory. The real implementation
   opens an OS-native folder picker which can't be automated by Playwright.

5. **Graceful skip**: Tests skip (not fail) when prerequisites aren't met
   (`SAGE_SKIP_E2E=1`, stub fails to start, Electron not built). This allows
   the test file to exist in CI without blocking unrelated pipelines.
