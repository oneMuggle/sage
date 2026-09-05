Status: DONE_WITH_CONCERNS

Commits:
- ed572d84 test(update): add integration coverage for upgrade flows
- ac16476b test(update): harden integration test isolation

Implementation:
- Added `electron/tests/updateIntegration.test.ts` with 14 deterministic integration tests covering all six required scenarios.
- Wired real `StateManager`, `ConfigManager`, and `UpdateManager` instances against per-test `mkdtemp()` directories.
- Mocked Electron app lifecycle methods, `electron-updater`, network `fetch`, and health-check results while exercising real state/config persistence and install/rollback filesystem transitions.
- Hardened test isolation by using optional temp-directory paths, cleaning only directories successfully created by `mkdtemp()`, resetting shared mock call history, and restoring `process.execPath` only when it was saved.
- Covered manual check/download/install/restart, auto-download pending state, auto-install flow, health-failure auto-rollback at the three-failure threshold, manual rollback window acceptance/rejection, and stable/beta/alpha channel persistence and feed selection.
- Deferred Playwright coverage as requested because this task is scoped to integration tests and no Electron Playwright fixture is required here.

Verification:
- `npm run test:run -- electron/tests/update*.test.ts` — passed after isolation hardening, 6 files and 88/88 tests.
- Direct TypeScript check for the new test (`npx tsc --noEmit --target es2022 --module esnext --moduleResolution bundler --skipLibCheck --types vitest/globals electron/tests/updateIntegration.test.ts`) — passed after isolation hardening.
- `npm exec eslint electron/tests/updateIntegration.test.ts` — passed after isolation hardening.
- `git diff --check` — passed for committed task changes.
- `npm run build` — blocked by existing `electron/tests/*.test.ts` top-level `await` TS1378 errors under `tsconfig.electron.json`; the same pre-existing pattern affects updateConfig, updateHealthChecker, updateManager, and updateState tests, not only the new file.

Concerns:
- `UpdateManager` currently exposes strategy persistence but does not itself implement a scheduler/automatic trigger that calls `downloadUpdate()` or `installUpdate()` after `checkForUpdates()`. The auto-download and auto-install tests therefore verify the real component flow with those actions explicitly orchestrated, plus the persisted strategy, rather than claiming an absent production scheduler.
- The repository build configuration includes Vitest test files in the Electron TypeScript project despite using top-level `await`; resolving that project-wide configuration issue is outside Task 12.
