# Audit reliability remediation — PR summary

## Paired PRs / isolation

- Main: https://github.com/oneMuggle/sage/pull/903
- Win7: https://github.com/oneMuggle/sage/pull/904
- Dedicated repair worktrees; original checkout and its existing changes were not modified.
- Bases synchronized before PR creation: main `91d5dd96`, Win7 `770857e0`.
- No automatic merge, direct release-branch push, dependency upgrade or packaging changes.

## Implemented scope

1. **Scheduled tasks (#1–5):** effective disable; real target sessions; form reset; full edit/create contract; explicit persistent failed/succeeded attempt state; single-flight delivery. Failed one-shots pause with a visible error and require a warned manual retry.
2. **Wiki (#6):** failed/cancelled terminal cleanup, listener-error reporting and pending subscription deduplication.
3. **Chat (#7–9):** reserve before asynchronous lookup, keep real cancellation handles across remounts, dispose late subscriptions, single terminal cleanup, correct content/reasoning accumulation, and session-scoped cancellation fallback.
4. **Office (#10):** stop unsafe page-driven deletion. Legacy sweep IPC is a no-op; explicit tracked discard remains. Safe lease/age-aware staging GC is a follow-up, not implemented here.
5. **Snapshots (#11):** lock and SAVEPOINT protect replacement, including preservation of an outer transaction on failure.
6. **MCP (#12–14):** URL/header setup across UI/IPC/REST; masked header readback; URL preserved by PATCH; JSON string-array arguments; serialized, bounded HTTP session renewal. Never automatically replay tools/call.
7. **Updates (#15–18):** real authenticated database read and renderer IPC probes with deadlines; pre-window startup failure accounting; one failed launch counted once; installed-version marker guard; non-blocking telemetry; restore prepared installation when initial state persistence fails.

Detailed [finding matrix](2026-09-16-audit-reliability.md).

## Paired implementation commits

| Batch | Main | Win7 |
| --- | --- | --- |
| Initial safety fixes | `99e18ae7` | `a11aeb81` |
| Scheduled contracts | `d2679218` | `f6a273e2` |
| Chat reattachment/cancellation | `e5d4a446` | `4e8e7913` |
| MCP configuration/recovery | `4b5ee311` | `2aebeb63` |
| Genuine update health/recovery | `6899d3e9` | `b7ec7c99` |
| CI-discovered legacy schedule compatibility | `251f6c57` | `016d7918` |
| CI frontend follow-up: idle lookup / realistic launched-version fixture | `0b672ada` | `c8a29b6f` |

Win7 commits retain cherry-pick provenance. Range-diff was reviewed: behavioral changes match; Python typing differences preserve the Win7 baseline's Optional annotations.

## Final local validation

Each branch passed the combined suite after all changes above:

- **240 frontend/Electron tests across 23 files**.
- **110 backend tests** (main Python 3.11.16; Win7 Python 3.8.20).
- Frontend and Electron TypeScript checks.
- ESLint and Ruff on every changed TS/TSX/Python file; whitespace checks.

Frontend suite:

```powershell
node ../../node_modules/vitest/vitest.mjs run electron/__tests__/officeIpc.test.ts src/features/office/__tests__/useOfficeDocuments.test.ts src/features/wiki/__tests__/useWikiIngest.taskcenter.test.ts electron/tests/updateManager.test.ts src/features/scheduled/__tests__/CreateTaskModal.test.tsx src/pages/__tests__/ScheduledTasks.test.tsx src/shared/api/__tests__/scheduledClient.test.ts src/features/send-message/__tests__ src/shared/api/__tests__/chatApi.interrupt.test.ts src/shared/api/__tests__/chatApi.lifecycle.test.ts src/pages/__tests__/Chat.cancel-run.test.tsx src/pages/__tests__/Chat.inline-error.test.tsx src/pages/settings/__tests__/McpTab.test.tsx electron/tests/updateHealthChecker.test.ts electron/test_backend_auto_restart.test.ts
```

Backend suite (use the appropriate interpreter, not the host default Python):

```powershell
python -m pytest backend/tests/integration/test_legacy_scheduled_tasks_still_work.py backend/tests/integration/test_scheduled_api.py backend/services/__tests__/test_scheduler.py backend/tests/unit/test_audit_reliability.py backend/tests/api/test_mcp_routes.py backend/tests/unit/test_mcp_http_client.py backend/tests/unit/test_mcp_auth_headers.py -q
```

## CI finding and correction

The second-round full backend suites found exactly three failures, all in `test_legacy_scheduled_tasks_still_work.py`: old direct service callers omitted schedule.kind. Main had 7603 passed / 118 skipped; Win7 had 7761 passed / 135 skipped in the failing jobs. The code was corrected, NOT the legacy tests: infer missing kind from task_type for service callers, while explicit mismatch remains rejected and REST still requires kind. Both branches now pass all three original regressions in the combined local suite.

Those earlier CI runs are not green: main `35074468328`, Win7 `35074514888`. All their other applicable checks passed, including main E2E `35074468251`. New heads containing batches 3–5 and the compatibility correction require a fresh full CI run; do not treat historical passes as approval of the final heads.

## Full-frontend CI follow-up

Runs `35076713161` / `35076741914` exposed four frontend failures after batches 3–5. Three were a real idle-action regression: a pending reattachment lookup prematurely disabled /compact. The registry now reserves synchronously without marking a reply active until a stream is found, preserving both deduplication and idle actions. The original compact tests are unchanged, and the streaming-blocked compact regression remains covered.

The fourth test seeded installed state at 2.0.0 but left app.getVersion at 1.0.0. Its fixture now models a real 2.0.0 launch; the production installed-version safety guard was retained. The 30-test regression pack passes on both branches:

```powershell
node ../../node_modules/vitest/vitest.mjs run electron/tests/updateIntegration.test.ts src/pages/__tests__/Chat.compact-fork.test.tsx src/features/send-message/__tests__/useChat.reattach.test.tsx src/pages/__tests__/Chat.compact-fork-loading.test.tsx
```

A full local Windows run additionally exposed one pre-existing POSIX-only expected path in officePaths.test.ts (2320 tests passed, 1 failed, 3 skipped). Its expected path now uses the host path.resolve semantics, preserving the exact containment/segment assertion; production Office path code is unchanged.

Final CI status must be checked on the PR's current SHA, not the historical runs above.

## Safety boundaries / release gates

- Scheduled delivery does not promise cross-crash exactly-once behavior. Manual retry must first inspect the destination conversation because a failure can be ambiguous after commit.
- HTTP MCP tool calls are never automatically replayed, even after session renewal. Inspect the result before retrying side-effecting tools.
- Office unsafe deletion is closed, but orphan cleanup may retain disk space until a separate ownership/lease-aware collector is designed.
- Database health proves a bounded read through the session repository, not every storage subsystem or every write path. IPC health is an actual read-only renderer round trip, not an unconditional stub.
- Local tests reuse parent node_modules; no clean dependency installation was performed. Python 3.8 testing on this host is not actual Windows 7 OS certification.
- Real packaged installer/rollback, actual Win7, platform-specific desktop behavior and exhaustive application E2E remain release checks. No merge or release is authorized by this document.
