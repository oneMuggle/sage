Status: DONE_WITH_CONCERNS

Commits:
- 9f5bff0e feat: expose update operations over electron ipc

Implementation:
- Added `electron/updateIpc.ts` with six trusted-renderer update invoke handlers, input validation, state/progress relay, duplicate-registration protection, and cleanup.
- Added `UpdateManager.setStrategy()` with immutable config persistence.
- Wired the app-level update manager and IPC cleanup into `electron/main.ts`.
- Exposed a typed `updates` preload namespace using only `ipcRenderer.invoke()` and `ipcRenderer.on/off()`.
- Added shared `ElectronAPI.updates` and update event types.
- Added focused IPC and preload tests covering success, authorization, validation, propagation, forwarding, and cleanup.

Verification:
- `npm run test:run -- electron/tests/updateIpc.test.ts` — passed, 6/6 tests.
- Update focused suites (`updateIpc.test.ts` + `updateManager.test.ts`) — passed, 58/58 tests.
- Electron test suite — 282/291 passed; 9 existing logger/log IPC failures caused by the environment's Electron installation error and `/mock/userData` permission failure, outside Task 9.
- TypeScript check — blocked by existing top-level `await` errors in `electron/tests/updateConfig.test.ts`, `updateHealthChecker.test.ts`, `updateManager.test.ts`, and `updateState.test.ts`; no remaining Task 9-specific type error.
- ESLint — passed for all Task 9 changed files.

Concerns:
- Full Electron suite and repository Electron TypeScript check remain blocked by pre-existing environment/configuration failures described above.

---

## Fix Round 1 (2026-09-05)

Addresses review findings from `task-9-review.md` (2 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW).

### CRITICAL fixes

**C1 — State event relay broken:** Removed the redundant `ipcMain.on('update:state-changed', ...)` listener and `stateChangedListener` from `updateIpc.ts`. The relay is correctly handled by `sendToRenderer` in `main.ts:1210-1212`, which directly calls `mainWindow?.webContents.send()`. The trusted-renderer validation was misplaced — `sendToRenderer` already targets the trusted `mainWindow`. Cleanup no longer calls `ipcMain.off()`. Updated tests to validate the actual relay path (via `onDownloadProgress` callback → `sendToRenderer`) and added a test confirming `ipcMain.on` is NOT called.

**C2 — Shared Electron API declaration uncompilable:** Removed the broken `import type { UpdateElectronApiBridge } from '../../../electron/updateIpc'` (the type is defined locally in the .d.ts). Added `import type { UpdateStateChangedEvent } from '../../../electron/updateIpc'` so the reference at line 147 resolves.

### HIGH fixes

**H1 — UpdateManager top-level instantiation:** Changed `const updateManager = new UpdateManager()` to `let updateManager: UpdateManager | null = null` at module scope, with lazy initialization inside `registerIpcHandlers()` after `app.whenReady()`.

**H2 — mainWindow closure capture:** Added a comment documenting that `mainWindow` is captured by closure and that `setMainWindow()` updates the reference, so the callback always reads the current live window.

**H3 — UpdateStateChangedEvent lacks discriminated tag:** Changed the union from `{ state: UpdateState } | { percent: number }` to `{ type: 'state'; state: UpdateState } | { type: 'progress'; percent: number }`. Updated progress emission in `updateIpc.ts` and all test assertions.

### MEDIUM fixes

**M2 — Test validates incorrect event model:** Fixed alongside C1 — test now validates the actual relay path via `onDownloadProgress` callback.

**M3 — WeakMap degenerates to Map:** Replaced `const registrations = new WeakMap<object, () => void>()` with `let currentCleanup: (() => void) | null = null`.

**M4 — removeHandler/off marked optional:** Simplified `UpdateIpcMain` to `Pick<IpcMain, 'handle' | 'removeHandler'>` (removed `on`/`off` since the `ipcMain.on` relay was removed). No optional markers remain.

**M1 — setStrategy non-atomic:** Added a TODO comment in `updateManager.ts:211-212` acknowledging the limitation. Atomic config is deferred to Task 10.

### LOW fixes

**L1 — Rollback reason not uniformly trimmed:** Changed to `(payload === undefined ? 'manual' : String(payload)).trim()` — uniform coercion and trim. Updated tests: numeric `123` now coerces to `"123"` (valid).

**L2 — Redundant `as` assertion:** Removed `as Promise<CheckResult>` from `checkForUpdates()` return. Also removed the now-unused `CheckResult` import.

**L3 — Redundant import:** Fixed alongside C2.

### Verification

- `npx vitest run electron/tests/updateIpc.test.ts` — **8/8 passed** (was 6/6, added 2 new tests).
- `npx vitest run electron/tests/` — **73/73 passed**, no regressions.
- `npx tsc --noEmit --project tsconfig.electron.json` — no new errors in changed files (pre-existing baseline errors in test files unchanged).
- `npx eslint electron/updateIpc.ts electron/main.ts electron/preload.ts electron/tests/updateIpc.test.ts` — **clean**.

### Files changed

- `electron/updateIpc.ts` — discriminated union, removed broken relay, simplified type, uniform trim, removed unused import.
- `electron/main.ts` — lazy UpdateManager init, documented mainWindow closure.
- `electron/updateManager.ts` — added TODO for non-atomic setStrategy.
- `src/shared/types/electron-api.d.ts` — fixed broken imports.
- `electron/tests/updateIpc.test.ts` — updated for discriminated union, new relay test, no-ipcMain.on test, uniform trim test.
