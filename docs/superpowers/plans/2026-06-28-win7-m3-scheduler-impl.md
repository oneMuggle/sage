# win7 M3 Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port main's simple scheduler (user-facing scheduled messages) byte-for-byte to `release/win7`, enabling win7 users to create/run/manage once or recurring scheduled messages that fire into target chat sessions.

**Architecture:** Backend `SchedulerService` wraps APScheduler `BackgroundScheduler` with JSON persistence (`scheduled_tasks.json`, atomic write) + thread safety. On fire, inserts a system-role message into the target session via `MessageRepository.insert`. Frontend Zustand store + IPC client (via generic `sage:invoke` backend proxy — no electron modifications needed) + UI (CronExpressionPicker, CreateTaskModal, ScheduledTasks page, Sidebar nav item, ChatInput 定时 button).

**Tech Stack:**
- Backend: Python 3.10, FastAPI, APScheduler 3.10.4, croniter, pydantic 2.x
- Frontend: React 18, TypeScript, Zustand 4.4.7, vitest, @testing-library/react, lucide-react, sonner
- Storage: `backend/data/scheduled_tasks.json` — UTC epoch ms, atomic write via tempfile + os.replace

## Global Constraints

From spec `2026-06-28-win7-m3-scheduler-design.md` and project rules:

- **Byte-for-byte port** from `main` branch (same py3.10 + pydantic 2.x env — no pydantic 1.x adaptation)
- **Python env**: `sage-backend` conda env (`/home/fz/anaconda3/envs/sage-backend/bin/python`) — Python 3.10 + pydantic 2.13.4
- **Frontend env**: Node 25.9.0 via nvm (`/home/fz/.nvm/versions/node/v25.9.0/bin/node`)
- **Coverage**: `scheduler.py` ≥ 95%, `cronValidator.ts` ≥ 95%, `scheduledClient.ts` ≥ 90%, overall frontend ≥ 85%, overall backend ≥ 85%
- **No electron modifications** — `sage:invoke` is a generic backend proxy, scheduled commands flow through automatically
- **Branch**: `feat/win7-m3-scheduler` (single branch, 10 commits)
- **Timezone**: UTC epoch ms in storage; `Intl.DateTimeFormat()` for display
- **i18n**: Win7 self-built `useI18n()` hook (M1) — compatible with main's `const { t } = useI18n()` pattern
- **TDD**: For byte-for-byte port tasks, main's tests are ported AS the RED step; implementation is ported as the GREEN step
- **Atomic file writes**: tempfile + os.replace for `scheduled_tasks.json`
- **Error contract**: Never throw to UI from scheduler fire loop; surface via store.error + toast

## File Structure

**New files (backend):**
- `backend/services/scheduler.py` — APScheduler wrapper + persistence (377 lines, from main)
- `backend/services/__init__.py` — package init
- `backend/services/__tests__/test_scheduler.py` — SchedulerService tests (490 lines, from main)
- `backend/api/scheduled_router.py` — REST API (166 lines, from main)
- `backend/tests/integration/test_scheduled_api.py` — Router integration tests (158 lines, from main)

**New files (frontend):**
- `src/features/scheduled/cronValidator.ts` — cron validation (119 lines, from main)
- `src/features/scheduled/__tests__/cronValidator.test.ts` — validator tests (87 lines)
- `src/shared/api/scheduledClient.ts` — IPC client (37 lines, from main)
- `src/shared/api/__tests__/scheduledClient.test.ts` — client tests (71 lines)
- `src/entities/scheduled/taskStore.ts` — Zustand store (68 lines, from main)
- `src/entities/scheduled/__tests__/taskStore.test.ts` — store tests (107 lines)
- `src/features/scheduled/CronExpressionPicker.tsx` — cron picker UI (61 lines, from main)
- `src/features/scheduled/__tests__/CronExpressionPicker.test.tsx` — picker tests (46 lines)
- `src/features/scheduled/CreateTaskModal.tsx` — create/edit modal (203 lines, from main)
- `src/features/scheduled/__tests__/CreateTaskModal.test.tsx` — modal tests (142 lines)
- `src/pages/ScheduledTasks.tsx` — list page (139 lines, from main)
- `src/pages/__tests__/ScheduledTasks.test.tsx` — page tests (49 lines)

**Modified files:**
- `backend/requirements.txt` — add `apscheduler==3.10.4`
- `backend/requirements-py38.txt` — add `apscheduler==3.10.4` (dual-branch consistency)
- `backend/main.py` — mount scheduler in lifespan + mount router + shutdown
- `src/shared/api/types.ts` — append `ScheduledTask`, `CreateTaskInput`, `UpdateTaskInput`, `Schedule`, `ScheduleKind` types
- `src/shared/lib/i18n/zh.ts` — add 28 scheduled/cron keys
- `src/shared/lib/i18n/en.ts` — add 28 scheduled/cron keys
- `src/App.tsx` — add `/scheduled` route
- `src/widgets/layout/Sidebar.tsx` — add Clock nav item for scheduled tasks
- `src/widgets/chat/ChatInput.tsx` — add 定时 button next to send

---

## Task 1: Backend — add APScheduler dependency + scaffold

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-py38.txt`
- Create: `backend/services/__init__.py`
- Create: `backend/services/__tests__/` directory

**Interfaces:** None (deps + scaffold only)

- [ ] **Step 1: Add apscheduler line to requirements.txt**

Append to `backend/requirements.txt` (after the last existing dep):

```
# Scheduled tasks (M3)
apscheduler==3.10.4
```

- [ ] **Step 2: Add same line to requirements-py38.txt**

Append to `backend/requirements-py38.txt` (maintains dual-branch dep consistency per CLAUDE.md):

```
# Scheduled tasks (M3)
apscheduler==3.10.4
```

- [ ] **Step 3: Create services package init**

```bash
touch backend/services/__init__.py
mkdir -p backend/services/__tests__
touch backend/services/__tests__/__init__.py
```

- [ ] **Step 4: Verify apscheduler imports**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -c "from apscheduler.schedulers.background import BackgroundScheduler; from apscheduler.triggers.cron import CronTrigger; from apscheduler.triggers.date import DateTrigger; import croniter; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/requirements-py38.txt backend/services/__init__.py backend/services/__tests__/__init__.py
git commit -m "build(backend): add apscheduler 3.10.4 for M3 scheduler"
```

---

## Task 2: Backend — port SchedulerService + tests from main

**Files:**
- Create: `backend/services/scheduler.py` (byte-for-byte from `main:backend/services/scheduler.py`, 377 lines)
- Create: `backend/services/__tests__/test_scheduler.py` (byte-for-byte from `main:backend/services/__tests__/test_scheduler.py`, 490 lines)

**Interfaces:**
- Consumes: APScheduler `BackgroundScheduler`, `CronTrigger`, `DateTrigger`, `croniter`, `MessageRepository` (mocked in tests), `SessionRepository` (mocked in tests)
- Produces: `SchedulerService` class, `ScheduledTask` dataclass, `TaskNotFoundError`, `ValidationError`, `get_scheduler_service()`, `init_scheduler_service()`

- [ ] **Step 1: Copy scheduler.py from main**

```bash
cd /home/fz/project/sage
git show main:backend/services/scheduler.py > backend/services/scheduler.py
```

- [ ] **Step 2: Copy test_scheduler.py from main**

```bash
git show main:backend/services/__tests__/test_scheduler.py > backend/services/__tests__/test_scheduler.py
```

- [ ] **Step 3: Run tests — verify GREEN**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py -v --no-header`
Expected: ~17 tests pass (TestLoadOnInit, TestAddTask, TestUpdateTask, TestDeleteTask, TestRunNow, TestLifecycle)

- [ ] **Step 4: Verify coverage >= 95%**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py --cov=backend.services.scheduler --cov-report=term-missing --no-header`
Expected: `scheduler.py ... 95%` or higher

- [ ] **Step 5: Commit**

```bash
git add backend/services/scheduler.py backend/services/__tests__/test_scheduler.py
git commit -m "feat(backend): port SchedulerService + tests from main (M3)"
```

## Task 3: Backend — port scheduled_router + integration tests from main

**Files:**
- Create: `backend/api/scheduled_router.py` (byte-for-byte from `main:backend/api/scheduled_router.py`, 166 lines)
- Create: `backend/tests/integration/test_scheduled_api.py` (byte-for-byte from `main:backend/tests/integration/test_scheduled_api.py`, 158 lines)

**Interfaces:**
- Consumes: `SchedulerService`, `TaskNotFoundError`, `ValidationError` (from Task 2)
- Produces: `build_router(get_service)` factory returning `APIRouter` with 6 endpoints (health, list, create, update, delete, run)

- [ ] **Step 1: Copy scheduled_router.py from main**

```bash
cd /home/fz/project/sage
git show main:backend/api/scheduled_router.py > backend/api/scheduled_router.py
```

- [ ] **Step 2: Copy test_scheduled_api.py from main**

```bash
git show main:backend/tests/integration/test_scheduled_api.py > backend/tests/integration/test_scheduled_api.py
```

- [ ] **Step 3: Run integration tests — verify GREEN**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_scheduled_api.py -v --no-header`
Expected: ~10 tests pass (health, list, create recurring, reject bad cron, reject past at, update, update missing 404, delete, delete missing 404, run_now)

- [ ] **Step 4: Commit**

```bash
git add backend/api/scheduled_router.py backend/tests/integration/test_scheduled_api.py
git commit -m "feat(backend): port scheduled_router + integration tests from main (M3)"
```

---

## Task 4: Backend — wire scheduler into main.py lifespan

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `SchedulerService`, `init_scheduler_service`, `get_scheduler_service` (from Task 2), `build_router` (from Task 3), `MessageRepository`, `SessionRepository` (existing), existing `lifespan` async context
- Produces: scheduler initialised + started on app startup; router mounted at `/api/v1`; scheduler shut down on app exit

- [ ] **Step 1: Add imports to main.py**

Add immediately after existing imports (after `from backend.data.database import Database`):

```python
from backend.api.scheduled_router import build_router as build_scheduled_router
from backend.data.message_repo import MessageRepository
from backend.data.session_repo import SessionRepository
from backend.services.scheduler import (
    get_scheduler_service,
    init_scheduler_service,
)
```

- [ ] **Step 2: Initialise scheduler in lifespan startup**

Inside `lifespan` (after `app.state.db = db`, before any sweeper/worker block), add:

```python
    # M3: scheduled tasks service — load JSON, start APScheduler
    from pathlib import Path
    store_path = Path("backend/data/scheduled_tasks.json")
    scheduler_service = init_scheduler_service(
        store_path=store_path,
        message_repo=MessageRepository(),
        session_repo=SessionRepository(),
    )
    scheduler_service.start()
    app.state.scheduler = scheduler_service
    logger.info(
        "SchedulerService 已初始化并启动（%d 个任务）",
        len(scheduler_service.list_tasks()),
    )
```

- [ ] **Step 3: Mount scheduled router**

After the existing `if/elif/else` block that mounts `legacy_router` / `hex_router`, add (regardless of API mode):

```python
# M3: scheduled tasks — mounted for both API modes (independent feature)
app.include_router(build_scheduled_router(get_scheduler_service), prefix="/api/v1")
```

- [ ] **Step 4: Shut down scheduler in lifespan cleanup**

In the cleanup section after `yield`, before any orphan-stream cancellation:

```python
    # M3: stop APScheduler cleanly so jobs do not fire after shutdown
    if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
        app.state.scheduler.shutdown()
```

- [ ] **Step 5: Sanity import check**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.main import app; print(sorted([r.path for r in app.routes if 'scheduled' in r.path]))"`
Expected: prints `['/api/v1/scheduled/health', '/api/v1/scheduled/tasks', '/api/v1/scheduled/tasks/{task_id}', '/api/v1/scheduled/tasks/{task_id}/run']`

- [ ] **Step 6: Run full backend test suite — verify no regression**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/ --no-header -q`
Expected: all tests pass (no regression from existing test suite)

- [ ] **Step 7: Commit**

```bash
git add backend/main.py
git commit -m "feat(backend): mount scheduler in main.py lifespan + router (M3)"
```

## Task 5: Frontend — types + cronValidator + tests

**Files:**
- Modify: `src/shared/api/types.ts` (append ScheduledTask types)
- Create: `src/features/scheduled/cronValidator.ts` (byte-for-byte from `main:src/features/scheduled/cronValidator.ts`, 119 lines)
- Create: `src/features/scheduled/__tests__/cronValidator.test.ts` (byte-for-byte from main, 87 lines)

**Interfaces:**
- Consumes: nothing (pure additions)
- Produces: `ScheduleKind`, `Schedule`, `ScheduledTask`, `CreateTaskInput`, `UpdateTaskInput` types (for Tasks 6-9); `validateCronExpression`, `validateOneShotTimestamp`, `describeSchedule`, `CRON_PRESETS` (for Tasks 6-7)

- [ ] **Step 1: Create features/scheduled directory**

```bash
mkdir -p /home/fz/project/sage/src/features/scheduled/__tests__
```

- [ ] **Step 2: Append ScheduledTask types to types.ts**

Append the following block at the end of `src/shared/api/types.ts` (before final newline):

```typescript
// ─── Scheduled Tasks (M3) ───────────────────────────────

export type ScheduleKind = 'once' | 'recurring';

export type Schedule =
  | { kind: 'once'; at: number }
  | { kind: 'recurring'; cron: string };

export interface ScheduledTask {
  id: string;
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
  enabled: boolean;
  last_run?: number | null;
  next_run?: number | null;
  created_at: number;
}

export interface CreateTaskInput {
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
}

export interface UpdateTaskInput {
  name?: string;
  enabled?: boolean;
}
```

- [ ] **Step 3: Copy cronValidator.ts from main**

```bash
cd /home/fz/project/sage
git show main:src/features/scheduled/cronValidator.ts > src/features/scheduled/cronValidator.ts
```

- [ ] **Step 4: Copy cronValidator.test.ts from main**

```bash
git show main:src/features/scheduled/__tests__/cronValidator.test.ts > src/features/scheduled/__tests__/cronValidator.test.ts
```

- [ ] **Step 5: Run tests — verify GREEN**

Run: `npx vitest run src/features/scheduled/__tests__/cronValidator.test.ts`
Expected: ~17 tests pass

- [ ] **Step 6: Verify tsc — no new type errors**

Run: `cd /home/fz/project/sage && npx tsc --noEmit -p tsconfig.json 2>&1 | head -20`
Expected: no errors related to `types.ts` or `cronValidator.ts`

- [ ] **Step 7: Commit**

```bash
git add src/shared/api/types.ts src/features/scheduled/cronValidator.ts src/features/scheduled/__tests__/cronValidator.test.ts
git commit -m "feat(scheduled): types + cronValidator + tests (M3)"
```

---

## Task 6: Frontend — scheduledClient + taskStore + tests

**Files:**
- Create: `src/shared/api/scheduledClient.ts` (byte-for-byte from `main:src/shared/api/scheduledClient.ts`, 37 lines)
- Create: `src/shared/api/__tests__/scheduledClient.test.ts` (byte-for-byte from main, 71 lines)
- Create: `src/entities/scheduled/taskStore.ts` (byte-for-byte from `main:src/entities/scheduled/taskStore.ts`, 68 lines)
- Create: `src/entities/scheduled/__tests__/taskStore.test.ts` (byte-for-byte from main, 107 lines)

**Interfaces:**
- Consumes: `invoke` from `src/shared/api/desktopInvoke.ts` (already exists in win7 — verified); `ScheduledTask`, `CreateTaskInput`, `UpdateTaskInput` (from Task 5); `create` from `zustand`
- Produces: `scheduledClient` object with `list`, `create`, `update`, `delete`, `runNow` methods (for Tasks 7-9); `useScheduledTaskStore` Zustand hook (for Tasks 7-9)

**Note on IPC compatibility:** Main's `scheduledClient` imports `from './desktopInvoke'`. Win7 has this file at `src/shared/api/desktopInvoke.ts`. Win7's `invoke` uses the generic `sage:invoke` channel (`ipcRenderer.invoke('sage:invoke', { cmd, args })`) which transparently forwards to backend HTTP via `invokeBackend(cmd, args, BACKEND_URL)`. No electron modifications needed.

- [ ] **Step 1: Copy scheduledClient.ts from main**

```bash
cd /home/fz/project/sage
git show main:src/shared/api/scheduledClient.ts > src/shared/api/scheduledClient.ts
```

- [ ] **Step 2: Copy scheduledClient.test.ts from main**

```bash
git show main:src/shared/api/__tests__/scheduledClient.test.ts > src/shared/api/__tests__/scheduledClient.test.ts
```

- [ ] **Step 3: Create entities/scheduled directory + copy taskStore**

```bash
mkdir -p /home/fz/project/sage/src/entities/scheduled/__tests__
git show main:src/entities/scheduled/taskStore.ts > src/entities/scheduled/taskStore.ts
git show main:src/entities/scheduled/__tests__/taskStore.test.ts > src/entities/scheduled/__tests__/taskStore.test.ts
```

- [ ] **Step 4: Run tests — verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/scheduledClient.test.ts src/entities/scheduled/__tests__/taskStore.test.ts`
Expected: ~13 tests pass (6 scheduledClient + 7 taskStore)

- [ ] **Step 5: Verify tsc**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | head -20`
Expected: no new errors

- [ ] **Step 6: Commit**

```bash
git add src/shared/api/scheduledClient.ts src/shared/api/__tests__/scheduledClient.test.ts src/entities/scheduled/taskStore.ts src/entities/scheduled/__tests__/taskStore.test.ts
git commit -m "feat(scheduled): scheduledClient + taskStore + tests (M3)"
```

## Task 7: Frontend — CronExpressionPicker + CreateTaskModal + tests

**Files:**
- Create: `src/features/scheduled/CronExpressionPicker.tsx` (byte-for-byte from main, 61 lines)
- Create: `src/features/scheduled/__tests__/CronExpressionPicker.test.tsx` (byte-for-byte from main, 46 lines)
- Create: `src/features/scheduled/CreateTaskModal.tsx` (byte-for-byte from main, 203 lines)
- Create: `src/features/scheduled/__tests__/CreateTaskModal.test.tsx` (byte-for-byte from main, 142 lines)

**Interfaces:**
- Consumes: `validateCronExpression`, `validateOneShotTimestamp`, `CRON_PRESETS` (from Task 5); `useScheduledTaskStore` (from Task 6); `useI18n` from `src/shared/lib/i18n` (M1 — win7 self-built, signature-compatible); `ScheduledTask`, `CreateTaskInput` types (from Task 5); `sonner` `toast`; `lucide-react` icons
- Produces: `CronExpressionPicker` React component; `CreateTaskModal` React component (for Tasks 8-9)

- [ ] **Step 1: Copy CronExpressionPicker.tsx from main**

```bash
cd /home/fz/project/sage
git show main:src/features/scheduled/CronExpressionPicker.tsx > src/features/scheduled/CronExpressionPicker.tsx
```

- [ ] **Step 2: Copy CronExpressionPicker.test.tsx from main**

```bash
git show main:src/features/scheduled/__tests__/CronExpressionPicker.test.tsx > src/features/scheduled/__tests__/CronExpressionPicker.test.tsx
```

- [ ] **Step 3: Copy CreateTaskModal.tsx from main**

```bash
git show main:src/features/scheduled/CreateTaskModal.tsx > src/features/scheduled/CreateTaskModal.tsx
```

- [ ] **Step 4: Copy CreateTaskModal.test.tsx from main**

```bash
git show main:src/features/scheduled/__tests__/CreateTaskModal.test.tsx > src/features/scheduled/__tests__/CreateTaskModal.test.tsx
```

- [ ] **Step 5: Run tests — verify GREEN**

Run: `npx vitest run src/features/scheduled/__tests__/CronExpressionPicker.test.tsx src/features/scheduled/__tests__/CreateTaskModal.test.tsx`
Expected: ~10 tests pass (5 picker + 5 modal)

- [ ] **Step 6: Check for i18n/test-setup mismatches**

If any tests fail due to i18n (main uses `i18next` test setup, win7 uses self-built), adapt the test mocks to wrap components in win7's `<I18nProvider>`. Reference: `src/features/scheduled/__tests__/CreateTaskModal.test.tsx` already wraps in `<I18nProvider>` (imported from `../../../shared/lib/i18n`) — verify the import path matches win7's i18n export.

- [ ] **Step 7: Verify tsc**

Run tsc check, confirm no new errors in these files.

- [ ] **Step 8: Commit**

```bash
git add src/features/scheduled/CronExpressionPicker.tsx src/features/scheduled/__tests__/CronExpressionPicker.test.tsx src/features/scheduled/CreateTaskModal.tsx src/features/scheduled/__tests__/CreateTaskModal.test.tsx
git commit -m "feat(scheduled): CronExpressionPicker + CreateTaskModal + tests (M3)"
```

---

## Task 8: Frontend — ScheduledTasks page + i18n keys + tests

**Files:**
- Create: `src/pages/ScheduledTasks.tsx` (byte-for-byte from main, 139 lines)
- Create: `src/pages/__tests__/ScheduledTasks.test.tsx` (byte-for-byte from main, 49 lines)
- Modify: `src/shared/lib/i18n/zh.ts` — add 28 scheduled/cron keys
- Modify: `src/shared/lib/i18n/en.ts` — add 28 scheduled/cron keys

**Interfaces:**
- Consumes: `useScheduledTaskStore` (from Task 6); `describeSchedule` (from Task 5); `useI18n` (M1); `ScheduledTask` type (from Task 5); `CreateTaskModal` (from Task 7); `react-router-dom` `useNavigate`; `sonner` `toast`; `lucide-react` icons
- Produces: `ScheduledTasks` page component (for Task 9 route wiring)

- [ ] **Step 1: Copy ScheduledTasks.tsx from main**

```bash
cd /home/fz/project/sage
git show main:src/pages/ScheduledTasks.tsx > src/pages/ScheduledTasks.tsx
```

- [ ] **Step 2: Copy ScheduledTasks.test.tsx from main**

```bash
git show main:src/pages/__tests__/ScheduledTasks.test.tsx > src/pages/__tests__/ScheduledTasks.test.tsx
```

- [ ] **Step 3: Add 22 scheduled.* keys to zh.ts**

Append before the closing `} as const;` in `src/shared/lib/i18n/zh.ts`:

```typescript

  // ─── 定时任务 (M3) ───────────
  'scheduled.title': '定时任务',
  'scheduled.subtitle': '管理自动发送的消息',
  'scheduled.empty': '还没有定时任务，点击下方按钮创建一个。',
  'scheduled.create': '新建任务',
  'scheduled.edit': '编辑任务',
  'scheduled.field.name': '任务名称',
  'scheduled.field.type': '类型',
  'scheduled.field.type.once': '执行一次',
  'scheduled.field.type.recurring': '周期',
  'scheduled.field.cron': 'Cron 表达式',
  'scheduled.field.at': '执行时间',
  'scheduled.field.session': '目标会话',
  'scheduled.field.content': '发送内容',
  'scheduled.field.enabled': '启用',
  'scheduled.status.enabled': '已启用',
  'scheduled.status.disabled': '已停用',
  'scheduled.action.run_now': '立即执行',
  'scheduled.toast.create_fail': '创建失败',
  'scheduled.toast.update_fail': '更新失败',
  'scheduled.toast.delete_fail': '删除失败',
  'scheduled.confirm.delete': '确定要删除这个定时任务吗？',
  'scheduled.sidebar.title': '定时任务',
```

- [ ] **Step 4: Add 22 scheduled.* keys to en.ts**

Append before the closing `};` in `src/shared/lib/i18n/en.ts`:

```typescript

  // ─── Scheduled Tasks (M3) ─────
  'scheduled.title': 'Scheduled Tasks',
  'scheduled.subtitle': 'Manage automated messages',
  'scheduled.empty': 'No scheduled tasks yet — create one below.',
  'scheduled.create': 'New Task',
  'scheduled.edit': 'Edit Task',
  'scheduled.field.name': 'Task name',
  'scheduled.field.type': 'Type',
  'scheduled.field.type.once': 'Run once',
  'scheduled.field.type.recurring': 'Recurring',
  'scheduled.field.cron': 'Cron expression',
  'scheduled.field.at': 'Run at',
  'scheduled.field.session': 'Target session',
  'scheduled.field.content': 'Message content',
  'scheduled.field.enabled': 'Enabled',
  'scheduled.status.enabled': 'Enabled',
  'scheduled.status.disabled': 'Disabled',
  'scheduled.action.run_now': 'Run now',
  'scheduled.toast.create_fail': 'Failed to create task',
  'scheduled.toast.update_fail': 'Failed to update task',
  'scheduled.toast.delete_fail': 'Failed to delete task',
  'scheduled.confirm.delete': 'Delete this scheduled task?',
  'scheduled.sidebar.title': 'Scheduled Tasks',
```

- [ ] **Step 5: Add 6 cron.preset.* keys to both files**

Append after scheduled keys (same position) in `zh.ts`:

```typescript
  'cron.preset.hourly': '每小时',
  'cron.preset.daily08': '每天 08:00',
  'cron.preset.daily18': '每天 18:00',
  'cron.preset.weekday09': '工作日 09:00',
  'cron.preset.weeklyMon': '每周一 09:00',
  'cron.preset.monthly1st': '每月 1 日 09:00',
```

Append after scheduled keys in `en.ts`:

```typescript
  'cron.preset.hourly': 'Hourly',
  'cron.preset.daily08': 'Daily 08:00',
  'cron.preset.daily18': 'Daily 18:00',
  'cron.preset.weekday09': 'Weekdays 09:00',
  'cron.preset.weeklyMon': 'Weekly Mon 09:00',
  'cron.preset.monthly1st': 'Monthly 1st 09:00',
```

- [ ] **Step 6: Update TranslationKey type**

The `TranslationKey` type in win7's i18n is likely a union derived from the keys object (e.g., `keyof typeof zh`). If it's a manual union, add the 28 new keys. Verify via grep for `TranslationKey` in i18n files. If auto-derived, no change needed.

- [ ] **Step 7: Run tests — verify GREEN**

Run: `npx vitest run src/pages/__tests__/ScheduledTasks.test.tsx`
Expected: ~3-5 tests pass

- [ ] **Step 8: Run full frontend test suite — verify no regression**

Run: `npx vitest run`
Expected: all tests pass

- [ ] **Step 9: Verify tsc**

Run tsc check, confirm no new errors.

- [ ] **Step 10: Commit**

```bash
git add src/pages/ScheduledTasks.tsx src/pages/__tests__/ScheduledTasks.test.tsx src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(scheduled): ScheduledTasks page + 28 i18n keys + tests (M3)"
```

## Task 9: Win7-specific — Sidebar nav + ChatInput 定时 button + App route

**Files:**
- Modify: `src/widgets/layout/Sidebar.tsx` — add Clock nav item for /scheduled
- Modify: `src/widgets/chat/ChatInput.tsx` — add Clock button + `onSchedule` prop
- Modify: `src/pages/Chat.tsx` (or parent) — render CreateTaskModal, pass onSchedule to ChatInput
- Modify: `src/App.tsx` — add /scheduled route
- Create: `src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx` — adapted from main's test (32 lines)

**Interfaces:**
- Consumes: `ScheduledTasks` page (from Task 8); `CreateTaskModal` (from Task 7); `useScheduledTaskStore` (from Task 6); `lucide-react` `Clock` icon; `react-router-dom` `useNavigate`
- Produces: Sidebar nav item; ChatInput `onSchedule` callback; App `/scheduled` route

**Background:** Win7 Sidebar uses a `navItems` array (not main's section pattern). Win7 ChatInput is named `ChatInput.tsx` (main refactored to `InputCard`). This task adapts the integration to win7's actual structure.

- [ ] **Step 1: Add /scheduled route to App.tsx**

Edit `src/App.tsx`. Add import at top:

```typescript
import { ScheduledTasks } from './pages/ScheduledTasks';
```

Add route inside the `<Route path="/" element={<Layout />}>` block (after the knowledge route):

```tsx
          <Route path="scheduled" element={<ScheduledTasks />} />
```

- [ ] **Step 2: Add nav item to Sidebar.tsx**

Edit `src/widgets/layout/Sidebar.tsx`. Add `Clock` to lucide-react import:

```typescript
import { MessageSquare, Settings, Brain, BookOpen, Clock } from 'lucide-react';
```

Add entry to `navItems` array (after knowledge, before settings):

```typescript
  { path: '/scheduled', label: '定时任务', icon: Clock },
```

- [ ] **Step 3: Add Clock button + onSchedule prop to ChatInput.tsx**

Edit `src/widgets/chat/ChatInput.tsx`. Add to the component props interface:

```typescript
  onSchedule?: () => void;
```

Add `Clock` to lucide-react import:

```typescript
import { Image, Paperclip, BookOpen, Clock, Square, X } from 'lucide-react';
```

Add a button inside the `<div className="flex items-center gap-1 flex-shrink-0">` (after the BookOpen button around line 201):

```tsx
              {onSchedule && (
                <button
                  type="button"
                  onClick={onSchedule}
                  title="定时"
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                >
                  <Clock className="w-4 h-4" />
                </button>
              )}
```

- [ ] **Step 4: Wire Chat page to open CreateTaskModal on 定时 click**

Edit the Chat page (likely `src/pages/Chat.tsx`). Add state + modal:

```typescript
import { CreateTaskModal } from '../features/scheduled/CreateTaskModal';
import { useStore } from '../shared/lib/store';

// inside Chat component:
const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
const currentSessionId = useStore((s) => s.currentSessionId);

// pass to ChatInput:
<ChatInput
  {...existingProps}
  onSchedule={() => setScheduleModalOpen(true)}
/>

// render modal after ChatInput:
{scheduleModalOpen && currentSessionId && (
  <CreateTaskModal
    open={scheduleModalOpen}
    onClose={() => setScheduleModalOpen(false)}
    sessionId={currentSessionId}
  />
)}
```

- [ ] **Step 5: Adapt ChatInput.scheduled.test.tsx from main**

Main's test targets `InputCard` (main's refactored name). Win7 uses `ChatInput`. Create `src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`:

```typescript
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

function renderInput(props: Partial<React.ComponentProps<typeof ChatInput>> = {}) {
  return render(
    <I18nProvider>
      <ChatInput
        value=""
        onChange={() => {}}
        onSubmit={() => {}}
        isLoading={false}
        {...props}
      />
    </I18nProvider>,
  );
}

describe('ChatInput scheduled button', () => {
  it('renders schedule button when onSchedule is provided', () => {
    renderInput({ onSchedule: vi.fn() });
    expect(screen.getByTitle(/定时/i)).toBeTruthy();
  });

  it('clicking schedule button invokes onSchedule', () => {
    const onSchedule = vi.fn();
    renderInput({ onSchedule });
    fireEvent.click(screen.getByTitle(/定时/i));
    expect(onSchedule).toHaveBeenCalledTimes(1);
  });

  it('does not render schedule button when onSchedule is undefined', () => {
    renderInput();
    expect(screen.queryByTitle(/定时/i)).toBeNull();
  });
});
```

- [ ] **Step 6: Run tests — verify GREEN**

Run: `npx vitest run src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`
Expected: 3 tests pass

- [ ] **Step 7: Run full frontend test suite + tsc — verify no regression**

Run: `npx vitest run` then `npx tsc --noEmit -p tsconfig.json`
Expected: all tests pass; 0 new type errors

- [ ] **Step 8: Commit**

```bash
git add src/App.tsx src/widgets/layout/Sidebar.tsx src/widgets/chat/ChatInput.tsx src/pages/Chat.tsx src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx
git commit -m "feat(scheduled): wire Sidebar nav + ChatInput 定时 button + /scheduled route (M3)"
```

## Task 10: Full integration verification + PR + memory updates

**Files:**
- No new code — verification only
- Update: `CHANGELOG.md` (add M3 entry under [Unreleased])
- Update: `.superpowers/sdd/progress.md` (mark M3 complete)
- Update: `~/.claude/projects/-home-fz-project-sage/memory/sage-m3-scheduler-merged.md` (new memory file)

**Interfaces:** None (verification task)

- [ ] **Step 1: Run full backend test suite**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/ -q`
Expected: all tests pass (existing + new M3 tests ~27)

- [ ] **Step 2: Run backend coverage check**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py --cov=backend.services.scheduler --cov-report=term-missing`
Expected: `scheduler.py >= 95%`

- [ ] **Step 3: Run full frontend test suite**

Run: `npx vitest run`
Expected: all tests pass (existing + new M3 tests ~45)

- [ ] **Step 4: Run tsc type check**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: 0 errors (or no new errors vs baseline)

- [ ] **Step 5: Start backend + smoke test scheduled API**

```bash
# terminal 1: start backend
/home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &

# wait for startup, then:
curl -s http://127.0.0.1:8765/api/v1/scheduled/health
# Expected: {"status":"ok"}

curl -s http://127.0.0.1:8765/api/v1/scheduled/tasks
# Expected: []

# kill backend
kill %1
```

- [ ] **Step 6: Add CHANGELOG entry**

Edit `CHANGELOG.md`. Add under `[Unreleased]` section (or create if missing):

```markdown
### Added
- M3 Scheduler: user-facing scheduled messages (once/recurring) with CronExpressionPicker, CreateTaskModal, ScheduledTasks page, Sidebar nav, ChatInput 定时 button (M3 byte-for-byte port from main)
```

- [ ] **Step 7: Push feat branch + create PR**

```bash
git push -u origin feat/win7-m3-scheduler
gh pr create --title "feat(M3): port scheduler from main (byte-for-byte)" \
  --body "Byte-for-byte port of main's simple scheduler (user-facing scheduled messages).

Backend:
- SchedulerService (APScheduler 3.10.4 + JSON persistence)
- scheduled_router (6 endpoints under /api/v1/scheduled/*)
- main.py lifespan integration

Frontend:
- types + cronValidator + scheduledClient + taskStore
- CronExpressionPicker + CreateTaskModal + ScheduledTasks page
- 28 i18n keys (zh + en)
- Sidebar Clock nav item + ChatInput 定时 button + /scheduled route

Tests: ~27 backend + ~45 frontend, all pass
Coverage: scheduler.py >= 95%, cronValidator.ts >= 95%

Spec: docs/superpowers/specs/2026-06-28-win7-m3-scheduler-design.md"
```

- [ ] **Step 8: Wait for CI, then local merge + push release/win7**

After CI green + user review:

```bash
# Local merge (fast-forward)
git switch release/win7
git merge --ff-only feat/win7-m3-scheduler
git push origin release/win7

# Cleanup
git branch -d feat/win7-m3-scheduler
git push origin --delete feat/win7-m3-scheduler
```

- [ ] **Step 9: Update memory + ledger**

Create `~/.claude/projects/-home-fz-project-sage/memory/sage-m3-scheduler-merged.md` with M3 completion summary. Update MEMORY.md index. Update `.superpowers/sdd/progress.md` ledger marking M3 complete.

---

## Summary

**10 commits total:**

1. `build(backend): add apscheduler 3.10.4 for M3 scheduler`
2. `feat(backend): port SchedulerService + tests from main (M3)`
3. `feat(backend): port scheduled_router + integration tests from main (M3)`
4. `feat(backend): mount scheduler in main.py lifespan + router (M3)`
5. `feat(scheduled): types + cronValidator + tests (M3)`
6. `feat(scheduled): scheduledClient + taskStore + tests (M3)`
7. `feat(scheduled): CronExpressionPicker + CreateTaskModal + tests (M3)`
8. `feat(scheduled): ScheduledTasks page + 28 i18n keys + tests (M3)`
9. `feat(scheduled): wire Sidebar nav + ChatInput 定时 button + /scheduled route (M3)`
10. (verification + PR + cleanup — no commit)

**Estimated time:** 4-5 hours (mostly byte-for-byte copy + verification)

**Final deliverables:**
- 10 source files ported from main (byte-for-byte)
- 8 test files ported from main (byte-for-byte or adapted)
- 5 win7-specific integration modifications (App.tsx, Sidebar.tsx, ChatInput.tsx, Chat.tsx, i18n keys)
- ~27 new backend tests + ~45 new frontend tests
- Coverage: scheduler.py >= 95%, cronValidator.ts >= 95%
