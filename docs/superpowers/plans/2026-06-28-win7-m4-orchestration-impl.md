# win7 M4 Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port main's multi-agent orchestration layer byte-for-byte to `release/win7`, enabling win7 users to submit ultragoals that decompose into multi-task/multi-lane plans, execute via agent routing, and display on a real-time three-column LaneBoard.

**Architecture:** Backend `orchestration/` package (16 files, ~4500 lines) implements Planner (LLM-based task decomposition) → Router (capability/round-robin/load-based dispatch) → Executor (lane lifecycle management) → LaneBoard (real-time aggregation). SQLite persistence via 4 new tables (`orchestration_tasks/lanes/lane_events/teams`). Frontend 4 files: `Orchestration` page + `LaneBoard` widget + `laneBoardStore` (Zustand) + `orchestrationClient` (IPC/HTTP).

**Tech Stack:**
- Backend: Python 3.10, FastAPI, pydantic 2.x, SQLAlchemy/SQLite
- Frontend: React 18, TypeScript, Zustand 4.4.7, vitest, @testing-library/react
- Electron: preload + main IPC channels (4 new: `orchestration_list_lanes`, `orchestration_get_lane`, `orchestration_list_lane_events`, `orchestration_cancel_lane`)
- Storage: SQLite via `backend/data/database.py` (4 new tables + 7 indexes)

## Global Constraints

From spec `2026-06-28-win7-m4-orchestration-design.md` and project rules:

- **Byte-for-byte port** from `main` branch (same py3.10 + pydantic 2.x env — no pydantic 1.x adaptation)
- **Python env**: `sage-backend` conda env (`/home/fz/anaconda3/envs/sage-backend/bin/python`) — Python 3.10 + pydantic 2.13.4
- **Frontend env**: Node 25.9.0 via nvm (`/home/fz/.nvm/versions/node/v25.9.0/bin/node`)
- **Coverage**: ≥ 80% for all new modules (matches testing.md)
- **Branch**: `feat/win7-m4-orchestration` (single branch, ~10-12 commits)
- **TDD**: For byte-for-byte port tasks, main's tests are ported AS the RED step; implementation is ported as the GREEN step
- **Error contract**: All API endpoints return Pydantic response models; never throw raw exceptions to client
- **Immutable state**: Frontend store uses immutable updates (Zustand pattern)
- **Existing deps**: ~70% of M4 supporting dependencies already on win7 (from phase 9 sync) — do NOT re-port

## File Structure

**New files (backend orchestration package — 16 files, 4501 lines from main):**
- `backend/orchestration/__init__.py` — package init (2 lines)
- `backend/orchestration/models.py` — Task/Lane/Team/Agent dataclasses (398 lines)
- `backend/orchestration/task_registry.py` — Task CRUD + dep graph (195 lines)
- `backend/orchestration/lane_registry.py` — Lane CRUD + heartbeat (219 lines)
- `backend/orchestration/team_registry.py` — Team CRUD (175 lines)
- `backend/orchestration/planner.py` — LLM-based decomposition (295 lines)
- `backend/orchestration/router.py` — Task → Agent routing (325 lines)
- `backend/orchestration/executor.py` — Lane lifecycle (492 lines)
- `backend/orchestration/heartbeat.py` — Stale lane detection (110 lines)
- `backend/orchestration/lane_board.py` — Lane aggregation (486 lines)
- `backend/orchestration/events.py` — Event recording + streaming (252 lines)
- `backend/orchestration/permission.py` — Permission presets (106 lines)
- `backend/orchestration/policy_engine.py` — Typed policy decisions (346 lines)
- `backend/orchestration/approval_tokens.py` — Privileged dispatch tokens (246 lines)
- `backend/orchestration/ultragoal_store.py` — Director-only goal persistence (606 lines)
- `backend/orchestration/report_schema.py` — Review report schema (248 lines)

**New files (backend persistence + API — 2 files, ~900 lines from main):**
- `backend/data/orchestration_repo.py` — SQLite repositories (601 lines, win7 缺失)
- `backend/api/orchestration_router.py` — REST API (4 endpoints, ~300 lines)

**New files (backend tests — port from main, ~1500 lines):**
- `backend/tests/unit/test_orchestration_models.py` — Task/Lane/Team state transitions
- `backend/tests/unit/test_orchestration_e2e.py` — Task/Lane/Team registry integration
- `backend/tests/unit/test_orchestration_executor.py` — Lane lifecycle
- `backend/tests/unit/test_orchestrator_dispatch.py` — Router + Planner
- `backend/tests/unit/test_lane_board.py` — Lane aggregation
- `backend/tests/unit/test_orchestration_repo.py` — (or reuse `test_data_blackboard_repo.py` style)
- `backend/tests/integration/test_e2e_5lane_workflow.py` — 5-lane end-to-end
- `backend/tests/integration/test_routes_agents.py` — API endpoints
- `backend/tests/integration/test_routes_agents_toggle.py` — Agent toggle
- `backend/tests/integration/test_routes_agents_update.py` — Agent update

**New files (frontend — 4 files from main):**
- `src/pages/Orchestration.tsx` — Page shell (~16 lines)
- `src/entities/orchestration/laneBoardStore.ts` — Zustand store (~120 lines)
- `src/shared/api/orchestrationClient.ts` — IPC client (~35 lines)
- `src/widgets/orchestration/LaneBoard.tsx` — Three-column board (~150 lines)

**New files (frontend tests — port from main, ~300 lines):**
- `src/pages/__tests__/Orchestration.test.tsx`
- `src/entities/orchestration/__tests__/laneBoardStore.test.ts`
- `src/shared/api/__tests__/orchestrationClient.test.ts`
- `src/widgets/orchestration/__tests__/LaneBoard.test.tsx`

**Modified files (backend):**
- `backend/data/database.py` — append ~100 lines of orchestration DDL (4 tables + 7 indexes)
- `backend/main.py` — mount `orchestration_router` (2 lines: import + include_router)

**Modified files (frontend):**
- `src/App.tsx` (or `src/app/AppRoutes.tsx`) — add `/orchestration` route
- `src/widgets/layout/Sidebar.tsx` (or equivalent) — add Orchestration nav item
- `src/shared/api/types.ts` — append `Lane`, `LaneEvent`, `LaneStatus`, `LaneBoardGroup` types
- `electron/preload.ts` — add 4 `orchestration_*` IPC channels
- `electron/main.ts` — add 4 IPC handlers (invoke HTTP backend)

---

## Task 1: DB Schema + Persistence Layer (P1)

**Files:**
- Modify: `backend/data/database.py`
- Create: `backend/data/orchestration_repo.py`
- Create: `backend/tests/unit/test_orchestration_repo.py` (or reuse `test_data_blackboard_repo.py` style)

**Interfaces:**
- `TaskRepository`: `create(task) -> Task`, `get(task_id) -> Task | None`, `update(task) -> Task`, `delete(task_id) -> bool`, `list_by_team(team_id) -> list[Task]`, `list_by_status(status) -> list[Task]`, `find_ready_tasks() -> list[Task]`
- `LaneRepository`: `create(lane) -> Lane`, `get(lane_id) -> Lane | None`, `update(lane) -> Lane`, `update_heartbeat(lane_id, heartbeat) -> None`, `list_by_task(task_id) -> list[Lane]`, `list_by_status(status) -> list[Lane]`, `find_stale(max_age_secs) -> list[Lane]`
- `TeamRepository`: `create(team) -> Team`, `get(team_id) -> Team | None`, `update(team) -> Team`, `add_task(team_id, task_id) -> None`, `list_by_status(status) -> list[Team]`
- `LaneEventRepository`: `record(event) -> None`, `list_by_lane(lane_id) -> list[LaneEvent]`, `list_by_task(task_id) -> list[LaneEvent]`, `list_since(timestamp) -> list[LaneEvent]`

- [ ] **Step 1: Add 4 orchestration tables + 7 indexes to `database.py`**

Append to `backend/data/database.py` in `init_tables()` function (after existing tables, before function end):

```bash
# Get the exact lines to append from main
git show main:backend/data/database.py | sed -n '272,371p'
```

Append the DDL for:
- `orchestration_tasks` + `idx_orch_tasks_status` + `idx_orch_tasks_team`
- `orchestration_lanes` + `idx_orch_lanes_task` + `idx_orch_lanes_status`
- `orchestration_lane_events` + `idx_orch_events_lane` + `idx_orch_events_task`
- `orchestration_teams` + `idx_orch_teams_status`

- [ ] **Step 2: Verify DB schema by starting backend**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.data.database import get_database; db = get_database(); conn = db.get_connection(); cursor = conn.cursor(); cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'orchestration_%'\"); print(cursor.fetchall())"
```

Expected output: 4 table names.

- [ ] **Step 3: Port `orchestration_repo.py` byte-for-byte from main**

```bash
git show main:backend/data/orchestration_repo.py > backend/data/orchestration_repo.py
```

Verify the file is 601 lines:
```bash
wc -l backend/data/orchestration_repo.py
# Expected: 601
```

- [ ] **Step 4: Port tests and run (RED → GREEN already since ported)**

```bash
# Find and port the orchestration_repo tests from main
git ls-tree -r main --name-only | grep -i "test.*orchestration_repo\|test_orchestration_e2e" | head -5
```

Port the relevant test file(s) and run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_e2e.py -v
# Expected: all pass
```

- [ ] **Step 5: Commit P1**

```bash
git add backend/data/database.py backend/data/orchestration_repo.py backend/tests/
git commit -m "feat(orchestration): P1 DB schema + persistence layer (M4)"
```

---

## Task 2: Core Models + Registries (P2)

**Files:**
- Create: `backend/orchestration/__init__.py`
- Create: `backend/orchestration/models.py`
- Create: `backend/orchestration/task_registry.py`
- Create: `backend/orchestration/lane_registry.py`
- Create: `backend/orchestration/team_registry.py`
- Create: `backend/tests/unit/test_orchestration_models.py`

**Interfaces:**
- `Task` dataclass: `mark_running()`, `mark_completed(result)`, `mark_failed(error)`, `mark_blocked()`, `mark_stopped()` — each validates pre-state
- `TaskRegistry`: `create(task) -> Task`, `get(task_id) -> Task`, `update(task) -> Task`, `delete(task_id) -> bool`, `get_ready_tasks() -> list[Task]` (all blocked_by completed)
- `LaneRegistry`: `create(lane) -> Lane`, `get(lane_id) -> Lane`, `update_heartbeat(lane_id, hb) -> None`, `find_stale(max_age_secs) -> list[Lane]`
- `TeamRegistry`: `create_team(team) -> Team`, `get_team(team_id) -> Team`, `add_task(team_id, task_id) -> None`

- [ ] **Step 1: Port the 5 orchestration core files byte-for-byte from main**

```bash
for f in __init__.py models.py task_registry.py lane_registry.py team_registry.py; do
  git show main:backend/orchestration/$f > backend/orchestration/$f
done
```

Verify file sizes:
```bash
wc -l backend/orchestration/{__init__,models,task_registry,lane_registry,team_registry}.py
# Expected: 2, 398, 195, 219, 175
```

- [ ] **Step 2: Port `test_orchestration_models.py` byte-for-byte**

```bash
git show main:backend/tests/unit/test_orchestration_models.py > backend/tests/unit/test_orchestration_models.py
```

- [ ] **Step 3: Run models tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_models.py -v
# Expected: all pass
```

- [ ] **Step 4: Run e2e orchestration tests (exercises TaskRegistry + LaneRegistry + TeamRegistry)**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_e2e.py -v
# Expected: all pass
```

- [ ] **Step 5: Commit P2**

```bash
git add backend/orchestration/{__init__,models,task_registry,lane_registry,team_registry}.py backend/tests/unit/test_orchestration_models.py
git commit -m "feat(orchestration): P2 core models + registries (M4)"
```

---

## Task 3: Planner + Router + Events (P3)

**Files:**
- Create: `backend/orchestration/planner.py`
- Create: `backend/orchestration/router.py`
- Create: `backend/orchestration/events.py`
- Create: `backend/tests/unit/test_orchestrator_dispatch.py`

**Interfaces:**
- `Planner.decompose_request(request, context) -> Plan` (with `plan_id`, `team_id`, `tasks[]`, `original_request`, `reasoning`)
- `Router.route_task(task) -> RoutingDecision` (with `agent_id`, `lane_id`, `strategy_used`, `reasoning`)
- `DispatchStrategy`: `ROUND_ROBIN`, `CAPABILITY_BASED`, `LOAD_BASED`
- `EventRecorder.record(event) -> None`
- `EventStream.list_by_lane(lane_id) -> list[LaneEvent]`
- `LaneEvent` enum: STARTED/READY/RUNNING/BLOCKED/SUCCEEDED/FAILED/STOPPED/...

- [ ] **Step 1: Port planner, router, events byte-for-byte from main**

```bash
for f in planner.py router.py events.py; do
  git show main:backend/orchestration/$f > backend/orchestration/$f
done
wc -l backend/orchestration/{planner,router,events}.py
# Expected: 295, 325, 252
```

- [ ] **Step 2: Port `test_orchestrator_dispatch.py` byte-for-byte**

```bash
git show main:backend/tests/unit/test_orchestrator_dispatch.py > backend/tests/unit/test_orchestrator_dispatch.py
```

- [ ] **Step 3: Run dispatch tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestrator_dispatch.py -v
# Expected: all pass
```

- [ ] **Step 4: Commit P3**

```bash
git add backend/orchestration/{planner,router,events}.py backend/tests/unit/test_orchestrator_dispatch.py
git commit -m "feat(orchestration): P3 planner + router + events (M4)"
```

---

## Task 4: Executor + Heartbeat + LaneBoard (P4)

**Files:**
- Create: `backend/orchestration/executor.py`
- Create: `backend/orchestration/heartbeat.py`
- Create: `backend/orchestration/lane_board.py`
- Create: `backend/tests/unit/test_orchestration_executor.py`
- Create: `backend/tests/unit/test_lane_board.py`

**Interfaces:**
- `LaneExecutor(lane_registry, task_registry, event_recorder, agent_runner)` — manages lane lifecycle
- `LaneExecutor.start(lane)` — validates permissions, transitions READY→RUNNING, records events
- `LaneExecutor.complete(lane, result)` — RUNNING→SUCCEEDED
- `LaneExecutor.fail(lane, error)` — RUNNING→FAILED + applies RecoveryPolicy
- `HeartbeatMonitor(lane_registry, interval_secs=60, max_age_secs=180)` — background worker
- `HeartbeatMonitor.scan_once()` — finds stale lanes, marks them FAILED
- `LaneBoard(lane_registry, event_stream)` — aggregation queries
- `LaneBoard.list_lanes(status?, team_id?, limit) -> list[Lane]`
- `LaneBoard.get_lane_summary(lane_id) -> dict`
- `LaneBoard.board_stats() -> {active, blocked, finished}`

- [ ] **Step 1: Port executor, heartbeat, lane_board byte-for-byte**

```bash
for f in executor.py heartbeat.py lane_board.py; do
  git show main:backend/orchestration/$f > backend/orchestration/$f
done
wc -l backend/orchestration/{executor,heartbeat,lane_board}.py
# Expected: 492, 110, 486
```

- [ ] **Step 2: Port executor + lane_board tests byte-for-byte**

```bash
git show main:backend/tests/unit/test_orchestration_executor.py > backend/tests/unit/test_orchestration_executor.py
git show main:backend/tests/unit/test_lane_board.py > backend/tests/unit/test_lane_board.py
```

- [ ] **Step 3: Run executor + lane_board tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_executor.py backend/tests/unit/test_lane_board.py -v
# Expected: all pass
```

- [ ] **Step 4: Commit P4**

```bash
git add backend/orchestration/{executor,heartbeat,lane_board}.py backend/tests/unit/{test_orchestration_executor,test_lane_board}.py
git commit -m "feat(orchestration): P4 executor + heartbeat + lane_board (M4)"
```

---

## Task 5: Policy + Ultragoal + Approval + Report + Permission (P5)

**Files:**
- Create: `backend/orchestration/policy_engine.py`
- Create: `backend/orchestration/ultragoal_store.py`
- Create: `backend/orchestration/approval_tokens.py`
- Create: `backend/orchestration/report_schema.py`
- Create: `backend/orchestration/permission.py`

**Interfaces:**
- `PolicyEngine.evaluate(context: PolicyContext) -> PolicyDecisionEvent`
- `UltragoalStore.create_goal(goal) -> Ultragoal` — Director-only write
- `UltragoalStore.update_goal(goal_id, **kwargs)` — Director-only
- `UltragoalStore.checkpoint(goal_id)` — append-only ledger entry
- `UltragoalStore.worker_write_attempt(actor, action)` — raises `WorkerWriteDenied`
- `ApprovalTokenStore.create_token(...)`, `validate_token(token)`, `revoke_token(token)`
- `ReviewReport` dataclass — executor-generated typed review
- `PermissionChecker.validate(lane_permission, agent_action) -> bool`
- `PermissionPreset`: `implement`, `deploy`, `read_only`

- [ ] **Step 1: Port the 5 policy-related files byte-for-byte**

```bash
for f in policy_engine.py ultragoal_store.py approval_tokens.py report_schema.py permission.py; do
  git show main:backend/orchestration/$f > backend/orchestration/$f
done
wc -l backend/orchestration/{policy_engine,ultragoal_store,approval_tokens,report_schema,permission}.py
# Expected: 346, 606, 246, 248, 106
```

- [ ] **Step 2: Find and port any remaining M4-related tests from main**

```bash
git ls-tree -r main --name-only | grep -E "test_.*(policy|ultragoal|approval|report|permission)" | grep -v __pycache__
```

Port each test file byte-for-byte.

- [ ] **Step 3: Run all backend orchestration tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "orchestration or orchestrator or lane" -v
# Expected: all pass
```

- [ ] **Step 4: Run full backend test suite to verify no regressions**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -q
# Expected: 1192 + new tests pass, no regressions
```

- [ ] **Step 5: Commit P5**

```bash
git add backend/orchestration/{policy_engine,ultragoal_store,approval_tokens,report_schema,permission}.py backend/tests/
git commit -m "feat(orchestration): P5 policy engine + ultragoal + approval + report + permission (M4)"
```

---

## Task 6: API Router + main.py Integration (P6)

**Files:**
- Create: `backend/api/orchestration_router.py`
- Modify: `backend/main.py`
- Create: `backend/tests/integration/test_routes_agents.py`
- Create: `backend/tests/integration/test_routes_agents_toggle.py`
- Create: `backend/tests/integration/test_routes_agents_update.py`
- Create: `backend/tests/integration/test_e2e_5lane_workflow.py`

**Interfaces:**
- `build_router() -> APIRouter` — factory, creates internal `LaneRegistry` + `EventStream`
- `GET /api/v1/orchestration/lanes?status=&team_id=&limit=` → `list[LaneOut]`
- `GET /api/v1/orchestration/lanes/{lane_id}` → `LaneOut`
- `GET /api/v1/orchestration/lanes/{lane_id}/events` → `list[LaneEventOut]`
- `POST /api/v1/orchestration/lanes/{lane_id}/cancel` body=`CancelIn` → `LaneOut`
- `LaneOut`, `LaneHeartbeatOut`, `LaneEventOut`, `CancelIn` — Pydantic response models

- [ ] **Step 1: Port `orchestration_router.py` byte-for-byte**

```bash
git show main:backend/api/orchestration_router.py > backend/api/orchestration_router.py
```

- [ ] **Step 2: Modify `main.py` to mount the orchestration router**

Add to `backend/main.py` (near other router imports and `include_router` calls):

```python
from backend.api.orchestration_router import build_router as build_orchestration_router
# ...
app.include_router(build_orchestration_router())
```

- [ ] **Step 3: Port integration tests byte-for-byte**

```bash
for f in test_routes_agents.py test_routes_agents_toggle.py test_routes_agents_update.py test_e2e_5lane_workflow.py; do
  git show main:backend/tests/integration/$f > backend/tests/integration/$f 2>/dev/null
done
```

- [ ] **Step 4: Start backend and verify endpoints**

```bash
# Terminal 1: start backend
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py

# Terminal 2: verify endpoints
curl http://127.0.0.1:8765/api/v1/orchestration/lanes | jq .
# Expected: [] (empty list, no lanes created yet)

curl http://127.0.0.1:8765/health | jq .
# Expected: {"status": "ok"}
```

- [ ] **Step 5: Run integration tests**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_routes_agents*.py backend/tests/integration/test_e2e_5lane_workflow.py -v
# Expected: all pass
```

- [ ] **Step 6: Commit P6**

```bash
git add backend/api/orchestration_router.py backend/main.py backend/tests/integration/
git commit -m "feat(orchestration): P6 API router + main.py integration (M4)"
```

---

## Task 7: Frontend + Electron IPC (P7)

**Files:**
- Create: `src/pages/Orchestration.tsx`
- Create: `src/entities/orchestration/laneBoardStore.ts`
- Create: `src/shared/api/orchestrationClient.ts`
- Create: `src/widgets/orchestration/LaneBoard.tsx`
- Create: frontend test files (4 files)
- Modify: `src/App.tsx` (or `src/app/AppRoutes.tsx`) — add `/orchestration` route
- Modify: `src/widgets/layout/Sidebar.tsx` (or equivalent) — add nav item
- Modify: `src/shared/api/types.ts` — append `Lane`, `LaneEvent`, `LaneStatus`, `LaneBoardGroup` types
- Modify: `electron/preload.ts` — add 4 IPC channels
- Modify: `electron/main.ts` — add 4 IPC handlers

**Interfaces:**
- `orchestrationClient`: `{ listLanes(params), getLane(laneId), listLaneEvents(laneId), cancelLane(laneId, reason) }`
- `useLaneBoardStore`: `{ lanes, loading, error, teamIdFilter, load, refresh, cancel, applyEvent, computeBoard }`
- `LaneBoardGroup`: `{ active: Lane[], blocked: Lane[], finished: Lane[] }`
- `Lane`: `{ lane_id, task_id, agent_id?, status, created_at, started_at?, completed_at?, worktree?, heartbeat?, error?, permission_preset, metadata }`
- `LaneStatus`: `'created' | 'ready' | 'running' | 'blocked' | 'succeeded' | 'failed' | 'stopped' | 'cancelled'`

- [ ] **Step 1: Port the 4 frontend source files byte-for-byte**

```bash
git show main:src/pages/Orchestration.tsx > src/pages/Orchestration.tsx
git show main:src/entities/orchestration/laneBoardStore.ts > src/entities/orchestration/laneBoardStore.ts
git show main:src/shared/api/orchestrationClient.ts > src/shared/api/orchestrationClient.ts
mkdir -p src/widgets/orchestration
git show main:src/widgets/orchestration/LaneBoard.tsx > src/widgets/orchestration/LaneBoard.tsx
```

- [ ] **Step 2: Port the 4 frontend test files byte-for-byte**

```bash
# Find exact test paths from main
git ls-tree -r main --name-only | grep -E "orchestr.*test|test.*orchestr" | grep -E "\.(ts|tsx)$"
```

Port each byte-for-byte.

- [ ] **Step 3: Add types to `src/shared/api/types.ts`**

Append (from main's types.ts, grep for Lane/LaneEvent/LaneStatus/LaneBoardGroup):

```bash
git show main:src/shared/api/types.ts | grep -A 20 "export type LaneStatus\|export interface Lane \|export interface LaneEvent\|export interface LaneBoardGroup"
```

Append the extracted types to `src/shared/api/types.ts`.

- [ ] **Step 4: Add `/orchestration` route to App.tsx (or AppRoutes.tsx)**

```bash
# Find how M3 added /scheduled route
grep -n "scheduled\|ScheduledTasks" src/App.tsx src/app/AppRoutes.tsx 2>/dev/null
```

Add similar route entry for `/orchestration` → `<Orchestration />`.

- [ ] **Step 5: Add Sidebar nav item for Orchestration**

```bash
# Find how M3 added ScheduledTasks nav
grep -n "scheduled\|ScheduledTasks\|Clock" src/widgets/layout/Sidebar.tsx 2>/dev/null | head -10
```

Add similar nav entry for Orchestration (icon suggestion: `GitBranch` or `Workflow` from lucide-react).

- [ ] **Step 6: Add 4 Electron IPC channels to `electron/preload.ts`**

```bash
# Find how M3 added scheduled_* IPC channels
grep -n "scheduled_\|orchestration_" electron/preload.ts | head -10
```

Add 4 new channels mirroring M3's pattern:

```typescript
orchestration_list_lanes: (params) => ipcRenderer.invoke('sage:invoke', 'orchestration_list_lanes', { params }),
orchestration_get_lane: (laneId) => ipcRenderer.invoke('sage:invoke', 'orchestration_get_lane', { lane_id: laneId }),
orchestration_list_lane_events: (laneId) => ipcRenderer.invoke('sage:invoke', 'orchestration_list_lane_events', { lane_id: laneId }),
orchestration_cancel_lane: (laneId, reason) => ipcRenderer.invoke('sage:invoke', 'orchestration_cancel_lane', { lane_id: laneId, reason }),
```

- [ ] **Step 7: Add 4 IPC handlers to `electron/main.ts`**

```bash
# Find how M3 added scheduled_* handlers
grep -n "scheduled_\|orchestration_" electron/main.ts | head -10
```

Add 4 handlers that proxy to HTTP backend:

```typescript
ipcMain.handle('sage:invoke', async (event, method, args) => {
  if (method === 'orchestration_list_lanes') {
    const res = await fetch(`${BACKEND_URL}/api/v1/orchestration/lanes?${new URLSearchParams(args.params)}`);
    return res.json();
  }
  // ... similar for other 3 methods
});
```

- [ ] **Step 8: Run frontend tests**

```bash
cd /home/fz/project/sage
npm run test -- --run
# Expected: 399 + new tests pass
```

- [ ] **Step 9: Run TypeScript check**

```bash
npx tsc --noEmit
# Expected: 0 errors
```

- [ ] **Step 10: Run frontend build**

```bash
npm run build
# Expected: success
```

- [ ] **Step 11: Commit P7**

```bash
git add src/pages/Orchestration.tsx src/entities/orchestration/ src/shared/api/orchestrationClient.ts src/widgets/orchestration/ electron/ src/App.tsx src/widgets/layout/Sidebar.tsx src/shared/api/types.ts
git commit -m "feat(orchestration): P7 frontend + Electron IPC (M4)"
```

---

## Task 8: CHANGELOG + Memory + PR + Merge (P8)

**Files:**
- Modify: `CHANGELOG.md`
- Create: `~/.claude/projects/-home-fz-project-sage/memory/sage-m4-orchestration-merged.md`
- Modify: `~/.claude/projects/-home-fz-project-sage/memory/MEMORY.md`

- [ ] **Step 1: Update CHANGELOG.md**

Add to `[Unreleased]` section:

```markdown
### Added
- feat(orchestration): multi-agent coordination layer (M4) — 16 backend files + API router + DB schema + frontend (f1bde0a..HEAD)
```

- [ ] **Step 2: Run final comprehensive tests**

```bash
# Backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -q
# Expected: 1192 + new tests pass

# Frontend
npm run test -- --run
# Expected: 399 + new tests pass

# TypeScript
npx tsc --noEmit
# Expected: 0 errors

# Electron build
npm run tauri build 2>&1 | tail -20
# Expected: build succeeds
```

- [ ] **Step 3: Run code-review agent**

```
Use code-reviewer agent on the full M4 diff
```

Address any CRITICAL or HIGH issues.

- [ ] **Step 4: Create PR**

```bash
git push -u origin feat/win7-m4-orchestration
gh pr create --title "feat(orchestration): M4 multi-agent coordination layer" --body "..."
```

- [ ] **Step 5: Wait for CI + user review + merge**

```bash
gh pr checks <pr-number> --watch
# After CI green + user approval:
gh pr merge --merge
```

- [ ] **Step 6: Cleanup**

```bash
git switch release/win7
git pull --rebase origin release/win7
git branch -d feat/win7-m4-orchestration
git push origin --delete feat/win7-m4-orchestration
```

- [ ] **Step 7: Create memory file**

Create `~/.claude/projects/-home-fz-project-sage/memory/sage-m4-orchestration-merged.md` with:
- Commit list (P1-P8 commits)
- Key results (backend tests, frontend tests, coverage)
- Related specs/plans references

Update `MEMORY.md` index.

---

## Success Criteria Summary

| Criterion | Target |
|---|---|
| Backend pytest | 1192 + new (orchestration) tests pass, no regressions |
| Frontend vitest | 399 + new (orchestration) tests pass, no regressions |
| TypeScript | 0 errors |
| Electron build | Success |
| Backend coverage (new modules) | ≥ 80% |
| Frontend coverage (new modules) | ≥ 80% |
| API endpoints | 4/4 functional (`/api/v1/orchestration/*`) |
| Frontend routes | `/orchestration` accessible |
| IPC channels | 4/4 registered (`orchestration_*`) |
| Sidebar nav | Orchestration entry visible |
| code-review agent | No CRITICAL/HIGH issues |
| User review | Approved |
| CHANGELOG | [Unreleased] updated |
| Memory | `sage-m4-orchestration-merged.md` created |

---

## DoD Checklist (per spec)

- ✅ M4 design spec + impl plan committed
- ✅ `feat/win7-m4-orchestration` branch CI green
- ✅ Backend pytest: new tests pass + existing 1192 tests pass
- ✅ Frontend vitest: new tests pass + existing 399 tests pass + tsc 0 errors
- ✅ DB: 4 orchestration tables + 7 indexes in `database.py`
- ✅ API: 4 endpoints in `orchestration_router.py` functional
- ✅ `main.py` mounts orchestration router
- ✅ Electron: 4 IPC channels registered
- ✅ Sidebar: Orchestration nav entry
- ✅ Frontend: `/orchestration` route + page renders
- ✅ code-review agent passes (no critical/high)
- ✅ User review approved
- ✅ CHANGELOG.md updated
- ✅ Memory file created
