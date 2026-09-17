# Reliability audit PRs: batches 1 and 2

## Paired PRs

- Main: https://github.com/oneMuggle/sage/pull/903 (`fix/audit-reliability-main` -> `main`).
- Win7: https://github.com/oneMuggle/sage/pull/904 (`fix/audit-reliability-win7` -> `release/win7`).
- Both bases were fetched successfully before PR creation: main `91d5dd96`, Win7 `770857e0`.
- No automatic merging, direct release-branch pushes, dependency upgrades or packaging changes.

## Scope

Batch 1 prevents Office data loss by disabling unsafe list-driven deletion, makes working-memory snapshot replacement transactional, fixes scheduled disable and Wiki terminal cleanup, preserves HTTP MCP URLs during updates, and hardens rollback telemetry/compensation.

Batch 2 closes scheduled-task findings #2–5:

- Select a real target session; an empty/unavailable selection cannot submit. The page loads the actual session catalog.
- Rehydrate all editable form state when opening or switching tasks. Preserve unchanged timestamps despite minute-precision datetime controls. Revalidate future times at submit time.
- Persist create-enabled state and all editable task fields. Validate type/schedule consistency and five-field cron before mutation. Recompute next execution and replace scheduler jobs.
- Persist `last_attempt`, `last_status`, and `last_error` independently of successful `last_run`. Existing JSON records remain readable with defaults.
- Failed one-shots pause in an explicit failed state and survive restart. The UI shows the failure and confirms manual retry, warning users to inspect the target conversation first.
- Reject overlapping manual delivery and edits during an active delivery. Ignore queued callbacks from superseded schedules.

## Failure / retry policy

No automatic replay is introduced. A transport/storage exception may be ambiguous after commit, so exactly-once delivery is NOT claimed. Users explicitly confirm retry after inspecting the target conversation. Recurring tasks continue at their next regular occurrence; failed one-shots do not silently appear successful or automatically repeat.

## Compatibility and commits

- Main scheduled code: `d2679218`.
- Win7 scheduled code: `f6a273e2`, cherry-picked with provenance.
- Win7 conflicts were limited to typing declarations and resolved with `Optional[...]`, retaining existing Python 3.8-specific imports and annotations.
- Range-diff was reviewed: shared behavior matches; differences are existing typing compatibility and cherry-pick metadata.

## Validation

On each branch:

- 117 targeted frontend/Electron tests passed (7 files), covering both batches.
- 66 backend tests passed (scheduler service, REST integration and audit regressions).
- Main backend interpreter: Python 3.11.16. Win7 interpreter: Python 3.8.20.
- Frontend and Electron TypeScript checks passed; targeted ESLint and Ruff checks passed.
- Added tests cover disabled creation, full edit persistence/rescheduling, type mismatch, invalid sessions, persistent failed one-shots and manual retry, missing sessions, overlapping runs, stale callbacks, expired paused one-shot editing, unknown fields, form switching and actual session selection.

Commands from either worktree:

```powershell
node ../../node_modules/vitest/vitest.mjs run electron/__tests__/officeIpc.test.ts src/features/office/__tests__/useOfficeDocuments.test.ts src/features/wiki/__tests__/useWikiIngest.taskcenter.test.ts electron/tests/updateManager.test.ts src/features/scheduled/__tests__/CreateTaskModal.test.tsx src/pages/__tests__/ScheduledTasks.test.tsx src/shared/api/__tests__/scheduledClient.test.ts
python -m pytest backend/tests/integration/test_scheduled_api.py backend/services/__tests__/test_scheduler.py backend/tests/unit/test_audit_reliability.py -q
node ../../node_modules/typescript/bin/tsc --noEmit
node ../../node_modules/typescript/bin/tsc -p tsconfig.electron.json --noEmit
```

Use the branch-appropriate Python interpreter (it is not on PATH in this host). Frontend tooling reuses the parent checkout's installed dependencies, not a clean npm install. Python 3.8 tests ran on the current Windows host, NOT an actual Windows 7 machine. Packaged installation/rollback and full platform E2E remain unverified locally.

## CI monitoring

Before the batch-2 push, first-round CI had passed frontend, Ubuntu/Windows Electron builds and Electron smoke on both PRs. Main dependency audit and all three E2E stages (stub-smoke, stub-deep, live-boot) had passed. Backend jobs were still running. These results are historical, NOT proof that the new PR heads passed: every push requires checking the new SHA's runs.

## Remaining work

- Chat reattachment and cancellation (#7–9).
- MCP URL-based creation/UI, argument parsing and HTTP recovery (remaining #12–14).
- Real health probes and early startup recovery (#15–16).
- Dedicated ownership/age/lease-aware staging GC; do not re-enable the unsafe sweep.

The full audit is not closed. See [the finding matrix](2026-09-16-audit-reliability.md).
