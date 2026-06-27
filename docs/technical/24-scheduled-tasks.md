# 24 — Scheduled Tasks (Phase 8)

## Overview

Backend-driven scheduler that fires one-shot or recurring messages into
target chat sessions. UI exposes create/edit/delete/run-now via the
`/scheduled` page and a sidebar group.

## Architecture

- Backend: APScheduler `BackgroundScheduler` in `backend/services/scheduler.py`,
  mounted in `backend/api/scheduled_router.py` under `/api/v1/scheduled/*`.
  Persistence: `backend/data/scheduled_tasks.json` (atomic write).
- Frontend: Zustand store in `src/entities/scheduled/taskStore.ts`, IPC via
  `src/shared/api/scheduledClient.ts`. UI in `src/pages/ScheduledTasks.tsx`
  and `src/widgets/sidebar/sections/CronJobSection.tsx`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/scheduled/health` | Liveness check |
| GET | `/api/v1/scheduled/tasks` | List all tasks |
| POST | `/api/v1/scheduled/tasks` | Create |
| PATCH | `/api/v1/scheduled/tasks/{id}` | Update name/enabled |
| DELETE | `/api/v1/scheduled/tasks/{id}` | Delete |
| POST | `/api/v1/scheduled/tasks/{id}/run` | Run now |

## Storage

JSON file with schema `{ "version": 1, "tasks": [...] }`. Each task carries
`id, name, type, schedule, session_id, content, enabled, created_at,
last_run?, next_run?`. Writes use `tempfile` + `os.replace` (atomic).

## Timezone

All timestamps stored as UTC epoch milliseconds. Frontend displays via
`Intl.DateTimeFormat` in user locale.

## Error handling

- Bad cron: HTTP 422 with reason.
- Past `at`: HTTP 422.
- Missing session: HTTP 422.
- Missing task: HTTP 404.
- Per-job failure: logged, scheduler continues.

## Tests

| Module | Coverage target |
| --- | --- |
| `backend/services/scheduler.py` | >= 95% |
| `backend/api/scheduled_router.py` | >= 90% |
| `src/features/scheduled/cronValidator.ts` | >= 95% |
| `src/shared/api/scheduledClient.ts` | >= 90% |
| Overall | >= 85% |
