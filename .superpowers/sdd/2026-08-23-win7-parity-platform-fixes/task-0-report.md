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
