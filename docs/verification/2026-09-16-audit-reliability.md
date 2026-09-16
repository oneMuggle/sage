# Audit reliability remediation — batch 1

Date: 2026-09-16. This is a partial implementation, not closure of all 18 audit findings.

## Branch isolation and provenance

- Main worktree: `.worktrees/audit-reliability-main`, branch `fix/audit-reliability-main`.
- Win7 worktree: `.worktrees/audit-reliability-win7`, branch `fix/audit-reliability-win7`.
- Bases: refreshed `origin/main` at `91d5dd96`; refreshed `origin/release/win7` at `770857e0`.
- Initial fetch failed; a subsequent fetch succeeded before PR creation. Both private repair branches were rebased onto the refreshed remote bases without conflicts.
- Main code commit after rebase: `99e18ae7`; Win7 code commit after rebase: `a11aeb81`. Original paired commits were `54ef07c6` / `1d5d4064`; the Win7 cherry-pick provenance retains that original source.
- `git range-diff` shows the same code patch; only the cherry-pick provenance message differs.
- Original main checkout and its pre-existing uncommitted changes were left untouched. No release branch was merged or directly pushed; repair branches are submitted through separate PRs.
- No dependency versions, Python compatibility shims, release channels, or packaging configuration were changed.

## Status by audit finding

| ID | Status | Implementation / remaining work |
| --- | --- | --- |
| 1 | Fixed | Use `with suppress(JobLookupError)` to actually remove jobs; queued automatic callbacks recheck current enabled/existence state. Manual run semantics preserved. |
| 2 | Fixed in batch 2 | Real session selector and server-side existence validation; no default placeholder ID. |
| 3 | Fixed in batch 2 | Form fields rehydrate on open/task changes; preserved unchanged one-shot timestamps. |
| 4 | Fixed in batch 2 | Create enabled and PATCH type/schedule/content/session fields are aligned end-to-end. |
| 5 | Fixed in batch 2 | Persist attempted/failed/succeeded outcomes; failed one-shots pause for explicit, warned manual retry (no automatic replay or exactly-once claim). |
| 6 | Fixed | Wiki failed/cancelled events end the task and release listeners; listener registration errors surface visibly; reserve pending subscriptions to prevent duplicate registration. |
| 7 | Pending | Single-flight chat stream reattachment. |
| 8 | Pending | Store real reattachment cancel/finish handles and enforce exactly-once cleanup. |
| 9 | Pending | Resolve backend stream ID before cancelling a session without a frontend handle. |
| 10 | Mitigated / destructive path closed | Remove page-driven sweep. Retain old IPC as a no-op so stale callers cannot delete managed files. Explicit tracked import discard remains functional. A new lease/age-aware staging collector is NOT implemented. |
| 11 | Fixed | Lock spans snapshot replacement; SAVEPOINT rolls back only this operation on failure and preserves an outer transaction. Outermost RELEASE commits the replacement. |
| 12 | Partially fixed | HTTP URL preserved during pool PATCH, including disable. URL-based REST creation and full UI/config capability alignment are still pending. |
| 13 | Pending | Structured MCP arguments or correct quoting parser. |
| 14 | Pending | HTTP session-invalid/transport failure state and bounded reconnection without replaying ambiguous side-effecting calls. |
| 15 | Pending | Real DB/IPC readiness probes instead of health-check stubs. |
| 16 | Pending | Route pre-window backend startup failures through update recovery accounting. |
| 17 | Fixed | Rollback does not await telemetry; reporting has a 2-second abort signal and timer cleanup. |
| 18 | Fixed | Restore prepared installation if the first pending-install state write fails. |

## Deliberate safety trade-off

The old sweep could not prove orphanhood: both archive-filtered lists and active imports could omit real directories. No managed directory is now deleted by that endpoint, including apparently unknown directories. Crash leftovers may occupy disk until a dedicated staging collector with explicit ownership, expiration, active leases and quarantine is designed. This is safer than attempting garbage collection from a frontend list snapshot.

Back up any potentially affected Office workspace before recovery investigation. This patch prevents future deletion; it cannot recover files already removed by older builds.

## Validation

- Office regression tests were run BEFORE the production patch: six failures reproduced unsafe cleanup and page-driven deletion.
- After fixing, each branch passed 99 frontend/Electron tests across:
  - `electron/__tests__/officeIpc.test.ts`
  - `src/features/office/__tests__/useOfficeDocuments.test.ts`
  - `src/features/wiki/__tests__/useWikiIngest.taskcenter.test.ts`
  - `electron/tests/updateManager.test.ts`
- Each branch passed 46 backend tests:
  - `backend/tests/unit/test_audit_reliability.py`
  - `backend/services/__tests__/test_scheduler.py`
- Main backend runtime: Python 3.11.16. Win7-branch backend runtime: Python 3.8.20.
- Frontend and Electron TypeScript checks passed on both branches.
- Targeted ESLint, Ruff and diff whitespace checks are part of batch validation.
- Two existing update-test path assumptions were normalized with `path.resolve` to make actual Windows execution test the intended failure paths rather than POSIX-only strings.
- The old chmod-based destructive-sweep test was replaced with retention tests because destructive sweep is intentionally disabled, not because a failure was waived.

### Reproduction commands (from either worktree)

Frontend toolchain is reused read-only from the parent checkout; no clean lockfile installation was performed:

```powershell
node ../../node_modules/vitest/vitest.mjs run electron/__tests__/officeIpc.test.ts src/features/office/__tests__/useOfficeDocuments.test.ts src/features/wiki/__tests__/useWikiIngest.taskcenter.test.ts electron/tests/updateManager.test.ts
node ../../node_modules/typescript/bin/tsc --noEmit
node ../../node_modules/typescript/bin/tsc -p tsconfig.electron.json --noEmit
```

Select the appropriate Python interpreter:

```powershell
# Main
& D:/programmingSoftware/Anaconda3/envs/sage-backend/python.exe -m pytest backend/tests/unit/test_audit_reliability.py backend/services/__tests__/test_scheduler.py -q
# Win7 branch
& D:/programmingSoftware/Anaconda3/envs/sage-backend-py38/python.exe -m pytest backend/tests/unit/test_audit_reliability.py backend/services/__tests__/test_scheduler.py -q
```

## Remaining verification and next batch

This does not certify packaged Windows 7 execution, real installers/rollback, macOS/Linux installations, full backend suites, or full application E2E. Python 3.8 tests ran on the current Windows host, not a Windows 7 machine. Existing dependency deprecation warnings remain.

Next batches should preserve paired main/Win7 commits and tests:

1. Scheduled task contracts and failed-execution lifecycle (#2–5).
2. Chat reattachment/cancellation state machine (#7–9).
3. MCP creation/configuration and HTTP recovery (#12–14).
4. Genuine startup health checks and early-failure recovery (#15–16).
5. Safe staging collector (follow-up to #10), followed by packaging and platform E2E.

Batch 2 verification and PR scope: [scheduled contracts](2026-09-16-scheduled-contracts.md).
