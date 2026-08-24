# Task 0 Report: Stabilize Packaged Startup and Build Provenance

## Implementation Summary

- Added canonical `BackendLaunchPlan` fields (`command`, `args`, `cwd`, `env`) while retaining legacy launcher aliases for compatibility. Packaged Windows/Linux launches use bundled Python and package-root `PYTHONPATH`; packaged mode never falls back to conda.
- Added versioned build manifest contract (`manifestVersion: 1`) with `buildId`, `commit`, `branch`, `version`, `electronVersion`, and `pythonVersion`.
- Added packaged manifest loading with validation and deterministic development fallback. The Win7 Python bundler now writes `resources/build-manifest.json`; the Win7 release workflow validates all required fields.
- Added backend generation ownership contract keyed by `{ generation, pid, ownershipToken }`, plus pure supervisor helpers and focused tests.
- Added Electron single-instance locking, duplicate-start protection, generation guards for spawn errors, exits, health results, restart timers, reconnect events, and shutdown escalation.
- Changed backend readiness from port-only HTTP 200 to JSON health ownership validation. Electron accepts readiness only when status, PID, generation, ownership token, and build ID match the current process.
- Added additive backend `/health` metadata and explicit doctor runtime metadata. Doctor can run with a bundled interpreter/package root and reports the resolved runtime.
- Added UTF-8 child-process decoding with escaped-byte fallback and retained UTC ISO machine-readable logging behavior.
- Added CI focused command-contract tests and release-time manifest validation.
- Confirmed renderer command usage inspected for Task 0 parity; existing `COMMAND_ROUTES` coverage and `/api/v1` path guards remain green.
- The brief named `backend/tests/integration/test_lifespan_wiring.py`, but it did not exist in the worktree. Added a minimal integration contract test covering health ownership metadata instead of expanding into unrelated lifespan behavior.

## Tests and Checks

All commands were run from the isolated Task 0 worktree.

- `npm exec -- vitest run electron/__tests__/backendLauncher.test.ts electron/__tests__/backendSupervisor.test.ts electron/__tests__/commands.test.ts`
  - PASS: 3 files, 73 tests.
- `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli backend/tests/integration/test_lifespan_wiring.py -q`
  - PASS: 178 tests, 5 pre-existing Pydantic deprecation warnings.
- `npm exec -- tsc -p tsconfig.electron.json --noEmit`
  - PASS.
- `npm exec -- eslint electron/backendLauncher.ts electron/backendSupervisor.ts electron/buildManifest.ts electron/doctor.ts electron/main.ts electron/__tests__/backendSupervisor.test.ts`
  - PASS.
- `/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/cli/doctor.py backend/main.py backend/tests/integration/test_lifespan_wiring.py backend/tests/unit/cli/test_doctor.py`
  - PASS.
- `git diff --check`
  - PASS.

## Commit

Commit message: `fix(win7): stabilize packaged backend lifecycle`

Commit hash: `6034f7ed`.

## Unresolved Concerns

- No real packaged Windows 7 runtime or NSIS smoke test was available in this environment; the release workflow now validates the generated manifest, but bundled runtime execution still needs a Windows packaging run.
- The health envelope uses environment-provided build metadata and a process PID/token fence. It does not yet expose a separate capability list; that remains intentionally outside Task 0.
- The existing project test suite emits five Pydantic deprecation warnings; they are unrelated to this change.
- The Electron main-process module is not directly unit-tested because importing it requires the Electron runtime; pure launcher, supervisor, manifest, route, backend doctor, and health contracts are covered.

---

## Review Round 1 — Findings & Fixes

### Findings addressed

| # | Finding | Resolution |
|---|---|---|
| 1 | Single-instance lock failure must `return`/`short-circuit` after `app.quit`, not just call `app.quit` | `electron/main.ts` now calls `app.quit(); process.exit(0);` and `return`s immediately so the rest of `bootstrap()` does not continue spawning a backend in the losing instance. |
| 2 | `electron-builder.yml` `extraResources` must include `resources/build-manifest.json` with CI verification | `extraResources` now lists `resources/build-manifest.json` first with an explanatory comment; `ci.yml` adds a Linux `test -f release/linux-unpacked/resources/build-manifest.json` step and a Windows PowerShell `Test-Path` step on `release/win-unpacked/resources/build-manifest.json`. |
| 3 | `waitForBackend` must recheck current child/generation/PID/token and port before publishing ready | New helpers `isPortStillBoundByPid(port, expectedPid, timeoutMs)` (Unix `lsof -iTCP:<port> -sTCP:LISTEN` / Win32 `netstat -ano -p TCP`) and `isPortReleased(port, timeoutMs)`; `waitForBackend` rechecks `isCurrentGeneration(...)`, child liveness, and port binding under the expected PID before flipping `backendLifecycle='ready'` and emitting `backend:ready`. |
| 4 | `restart`/`shutdown` must await child exit and port release before respawn | `shutdownBackend()` is now async: SIGTERM, then SIGKILL after 3s, then polls `isPortReleased(200ms)` until the port drops; `scheduleBackendRestart()` awaits `shutdownBackend()` before spawning the next generation; `window-all-closed` and `before-quit` handlers await the same shutdown. |
| 5 | `doctor` must use the exact backend command/cwd/env/PYTHONPATH and must perform a real `import backend.main` rather than a directory-existence check | `backend/cli/doctor.run_doctor(...)` now takes optional `backend_command`, `backend_cwd`, `backend_env` mirroring the supervisor contract; PYTHONPATH is built as `package_root + backend_env.PYTHONPATH`; `_try_import_backend()` spawns `<interpreter> -c "import backend.main"` with the same cwd/env and a 5s timeout, returning `bool`. On POSIX (incl. conda envs) `PYTHONHOME` is **not** set — the comment notes it is only valid for the Win32 Python embeddable layout, otherwise it corrupts the conda prefix. The pre-existing `TestRunDoctor` was updated to use `sys.executable` + the real `<repo>/` package root so the probe actually exercises `import backend.main`. |
| 6 | Renderer readiness gate / `backend_not_ready` error for initial invokes | New `BackendNotReadyError` (`code='BACKEND_NOT_READY'`, 中文默认消息) thrown from the `sage:invoke` IPC handler when `backendLifecycle !== 'ready'`; `desktopInvoke.ts` short-circuits to that marker before any `ECONNREFUSED` branch; `BackendStatusBanner` now subscribes to the new `backend:starting` event (state `'starting'`) and transitions to `'ready'` on `backend:ready`. |
| 7 | Decode backend stdout/stderr with a per-stream incremental UTF-8 decoder | New `electron/incrementalUtf8Decoder.ts` exposing `createIncrementalUtf8Decoder(escapeByte?)` built on WHATWG `TextDecoder({ fatal: true, stream: true })` (cast to `TextDecoderOptions`) with `push()`, `close()`, `reset()`. Both stdout and stderr in `electron/main.ts` use one decoder each so multi-byte chars never break across chunk boundaries. |
| 8 | Lifecycle/Windows teardown tests where feasible | Added `electron/__tests__/incrementalUtf8Decoder.test.ts` (9 cases: ASCII, BMP 中文, 4-byte emoji, split chunks, mixed streams, close/reset, escape byte fallback) and `electron/__tests__/backendNotReadyError.test.ts` (4 cases: code marker, default message, custom override, `instanceof Error`). |

### Files changed (round 1)

```
.github/workflows/ci.yml                   |  35 ++++
backend/cli/doctor.py                      |  98 ++++++++-
backend/tests/unit/cli/test_doctor.py      |  24 ++-
electron-builder.yml                       |  10 +
electron/invoke.ts                         |  25 +++
electron/main.ts                           | 316 +++++++++++++++++++++++++----
src/shared/api/desktopInvoke.ts            |  16 +-
src/widgets/system/BackendStatusBanner.tsx |  56 +++--
electron/incrementalUtf8Decoder.ts         | +new
electron/__tests__/incrementalUtf8Decoder.test.ts | +new
electron/__tests__/backendNotReadyError.test.ts  | +new
```

### Tests and Checks

All commands were run from the same isolated Task 0 worktree (`fix/win7-packaged-supervisor`).

- `npm run lint` — 0 errors (5 pre-existing warnings in unrelated files, e.g. `ChatInput.tsx` exhaustive-deps).
- `npm exec -- tsc -p tsconfig.electron.json --noEmit` — PASS.
- `npm run typecheck` (renderer) — PASS.
- `npm exec -- vitest run electron/__tests__/incrementalUtf8Decoder.test.ts electron/__tests__/backendNotReadyError.test.ts electron/__tests__/backendLauncher.test.ts electron/__tests__/backendSupervisor.test.ts electron/__tests__/commands.test.ts` — PASS, 5 files, 86 tests.
- `npm exec -- vitest run electron/__tests__/` (full electron suite) — PASS, 17 files, 198 tests.
- `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli backend/tests/integration/test_doctor_cli.py` — PASS, 194 tests, 5 pre-existing Pydantic deprecation warnings.
- `/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/` — All checks passed.
- `git diff --check` — clean (no whitespace issues).

### Notes

- The failing pre-existing `TestRunDoctor::test_reports_explicit_runtime_and_package_root` was rewritten against the new contract: it now passes a real interpreter (`sys.executable`) and the real `<repo>/` package root so the `import backend.main` probe genuinely runs. Two follow-up adjustments were required to make this test green: (a) `_try_import_backend` now only sets `PYTHONHOME` on Win32 — on POSIX/conda the previous code corrupted the prefix and `import backend.main` returned 1; (b) `subprocess.run` gains `check=False` to satisfy Ruff `PLW1510` without changing behaviour (return code is still inspected via `result.returncode == 0`).
- `process.resourcesPath` is undefined under Vitest, so a previous draft `backendLifecycle.test.ts` that imported `electron/main.ts` was deleted rather than mocked.
- WHATWG `TextDecoderOptions` does not declare `stream` in the TS lib; both `new TextDecoder(...)` and `decoder.decode(value, { stream: true })` are cast as `TextDecoderOptions` with an inline comment, matching the upstream WHATWG spec.
