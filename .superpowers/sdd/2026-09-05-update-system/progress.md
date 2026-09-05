# SDD ledger — plan: docs/superpowers/plans/2026-09-05-update-system.md

## Pre-flight Scan

Scanning plan for conflicts before execution...

### Task Dependencies

- Task 1: Backend metadata models + service (no dependencies)
- Task 2: Backend API routes (depends on Task 1)
- Task 3: Client state + config management (no dependencies)
- Task 4: UpdateManager state machine (depends on Task 3)
- Task 5-12: Outlined but not detailed (to be expanded during execution)

### Interface Consistency Check

| Task | Produces | Consumed By | Consistency |
|------|----------|-------------|-------------|
| Task 1 | `UpdateManifest`, `FileMeta`, `UpdateMetadataService` | Task 2 | ✅ Models match API requirements |
| Task 2 | REST endpoints `/api/v1/updates/*` | Task 4 (client) | ✅ Endpoints match client fetch calls |
| Task 3 | `StateManager`, `ConfigManager` | Task 4 | ✅ Interfaces match UpdateManager usage |
| Task 4 | `UpdateManager.checkForUpdates()` | Task 5+ | ✅ Partial implementation, stubs for download/install |

### Global Constraints Verification

- ✅ Python 3.10 (main) — backend uses `sage-backend` conda env
- ✅ Node.js 25.9.0 — frontend uses nvm
- ✅ Electron 21.4.4 — locked for Win7
- ✅ HTTPS + SHA-512 — validated in `FileMeta` model
- ✅ State persistence: JSON in `app.getPath('userData')`
- ✅ Rollback window: 7 days default
- ✅ Auto-rollback threshold: 3 failures default
- ✅ Channels: stable, beta, alpha

### Scan Result

**Clean.** No conflicts found. All interfaces align. Global constraints are consistent across tasks.

---

## Task Execution Log

### Task 1: complete (commits 14ec6028..3b8077fd, review approved)

**Spec compliance:** ✅ — Implementation matches brief exactly
**Quality:** Approved with 3 minor issues (deferred to final review)

**Deferred minor findings:**
- `backend/tests/test_update_metadata.py:1` — unused `import json`
- Test file — no negative validator tests (validators' `raise ValueError` branches not exercised)
- `backend/services/update_metadata.py:21-23` — cache behaves differently for missing vs empty directories (inconsistent but not a bug)

### Task 2: complete (commits 3b8077fd..88458a9c, review approved)

**Spec compliance:** ✅ — All 3 endpoints, 4 files, 5 tests match brief exactly
**Quality:** Approved — clean code, proper error handling, correct FastAPI idioms
**Issues:** None

### Task 3: complete (commits 88458a9c..20dd6955, review approved)

**Spec compliance:** ✅ — All required interfaces, fields, defaults, and HMAC integrity implemented
**Adaptation:** ✅ Acceptable — vitest adaptation matches project convention (18+ existing tests use vitest)
**Quality:** Approved — clean code, correct HMAC, proper error handling
**Issues:** None

**Non-blocking observations for future tasks:**
- Test directory `electron/tests/` vs project convention `electron/__tests__/` (brief-level decision)
- Hardcoded HMAC dev fallback acceptable for local state (not security boundary)

### Task 4: fix round 1/5 in progress

**Review findings:** 3 HIGH, 2 MEDIUM, 2 LOW
- Strict semver/prerelease comparison and invalid input handling
- Correct Linux/Windows architecture mapping
- Runtime manifest/file metadata validation
- Persist `lastCheckTime` on 404
- Remove unused imports and add edge-case tests

### Task 4: fix round 2/5 in progress

**Open findings from scoped re-review:**
- Strict SemVer numeric identifiers still use `Number`, causing precision loss for legal large versions
- Architecture test assumes `arm64` is always unsupported and fails on macOS arm64

### Task 4: fix round 3/5 (3 addressed, 0 open; commit dc7b354f)

**Scoped re-review:** ✅ READY / APPROVED
- Darwin architecture whitelist corrected
- Architecture boundary test made deterministic across platforms
- No new regressions

### Task 4: complete (commits 20dd6955..dc7b354f, review clean)

### Task 5: complete (commits b8290c90..f4a1b041, review clean)

**Spec compliance:** ✅ — GenericProvider feed, metadata binding, channel preservation
**Quality:** Approved — 28 tests passing, comprehensive metadata validation

**Implementation:**
- Added `electron-updater` as runtime dependency
- Implemented `downloadUpdate()` with GenericProvider feed from manifest URL
- Extended `CheckedUpdate` with filename/sha512/size for metadata binding
- Added `getArtifactBasename()` for relative URL support (electron-updater returns relative filenames)
- Preserved channel (stable/beta/alpha) through updater feed configuration
- Persisted `pendingUpdate` with version and ISO `downloadedAt` timestamp
- Added `onDownloadProgress()` with unsubscribe support

**Security hardening (commit f4a1b041):**
- Bound manifest metadata to updater artifact (version + filename + sha512 + size validation)
- Prevents updater from downloading different artifact than what was checked
- Added comprehensive mismatch tests (version, filename, sha512, size)
- Added relative URL acceptance tests for electron-updater 6.8.9 behavior

**Verification:**
- 28/28 tests passing (was 18 originally, added 10 metadata binding tests)
- TypeScript check: passed
- ESLint: passed
- diff --check: passed

**Concerns (deferred to later tasks):**
- Pre-existing `typecheck:electron` blocked by test file top-level await + CommonJS conflict
- Code signature verification not implemented (currently presence check only)
- Real production release workflow (YAML generation, code signing) not configured

---

### Task 6: complete (commit 6de3535c, review approved)

**Spec compliance:** ✅ — installUpdate() + prepareForUpgrade() with cover upgrade semantics
**Quality:** Approved — 35 tests passing (7 new), all acceptance criteria covered

**Implementation:**
- `installUpdate()`: validates pendingUpdate, calls prepareForUpgrade, invokes quitAndInstall, commits state
- `prepareForUpgrade()`: removes stale `.prev`, writes `.prepare-rollback.bat` on Windows, renames install dir on Linux/macOS
- State update: currentVersion=pending, lastKnownGoodVersion=old, lastKnownGoodInstallDate=now, crashCount=0, pendingUpdate=null

**Verification:**
- 35/35 tests passing (was 28/28, added 7 cover upgrade tests)
- TypeScript check: passed
- ESLint: passed
- diff --check: passed

**Review findings:**
- No CRITICAL or HIGH issues
- 2 MEDIUM (informational): State commit after quitAndInstall (brief-level design), Linux rename while running (safe per Linux semantics)
- 2 LOW: POSIX mode on Windows (harmless), pre-existing typecheck blocked (Task 5)

**Concerns (deferred):**
- State commit after quitAndInstall: brief explicitly acknowledges, matches spec
- Pre-existing typecheck:electron blocked: documented in Task 5

---

### Task 7: complete (commits 8cb8f157..d7aa20e2, review approved)

**Spec compliance:** ✅ — LauncherHealthChecker + onAppStartup() + crash counter logic
**Quality:** Approved — 53 tests passing (12 new), all acceptance criteria covered

**Implementation:**
- `LauncherHealthChecker` class with 4 checkpoint methods (mainWindow 3s timeout, backend 10 retries × 1s, database stub, IPC stub)
- `onAppStartup()` method: version change → reset crashCount; check fail → increment; threshold hit → throw; check pass → reset
- Backend health check: 10 retries, 1s interval, 2s per-request timeout via AbortController
- Main window check: polls every 100ms for 3 seconds
- `lastRecordedVersion` field already present from Task 3

**Verification:**
- 53/53 tests passing (was 35/35, added 7 health checker + 5 manager startup tests)
- TypeScript check: passed
- ESLint: passed
- diff --check: passed

**Review findings:**
- No CRITICAL or HIGH issues
- 1 MEDIUM (fixed in d7aa20e2): Dead comment after throw — moved above throw
- 3 LOW (deferred): Missing combined test, void lint suppression, state mutation pattern

**Concerns (deferred):**
- `checkDatabaseAccessible()` and `checkCoreIpcResponsive()` are stubs (as specified in brief)
- Pre-existing typecheck:electron blocked (documented in Task 5)

---

### Task 8: complete (commit ccda9c8a, review approved)

**Spec compliance:** ✅ — All 11 acceptance criteria met
**Quality:** Approved — 52 tests passing (12 new), no CRITICAL/HIGH issues

**Implementation:**
- `rollback(reason)`: reports event, checks .prev, restores or reinstalls, updates state, restarts app
- `canManualRollback()`: checks 3 conditions (lastKnownGoodVersion exists, version differs, within window)
- `reportRollbackEvent()`: POSTs to backend fire-and-forget, ignores failures
- `reinstallFromPackage()`: spawns cached installer silently, waits for exit code 0
- `pathExists()` helper
- `onAppStartup()` updated to call `rollback()` when threshold reached (instead of just throwing)

**Verification:**
- 52/52 tests passing (was 40/40, added 12 rollback tests)
- TypeScript check: passed
- ESLint: passed

**Review findings:**
- No CRITICAL or HIGH issues
- 2 LOW (deferred): Test count discrepancy (52 vs brief's 53 — brief was off), minor `as` casts in tests

**Concerns (deferred):**
- Pre-existing typecheck:electron blocked (documented in Task 5)

---

### Task 9: complete (commits 9f5bff0e..53ee9679, review approved after fix round 1)

**Spec compliance:** ✅ — All 12 acceptance criteria met after fix round 1
**Quality:** Approved — 8/8 updateIpc tests passing, 73/73 full Electron suite, no regressions

**Implementation:**
- `electron/updateIpc.ts`: Dedicated update IPC module with 6 invoke handlers (check, download, install, rollback, can-rollback, set-strategy)
- `electron/main.ts`: Lazy-init UpdateManager inside `registerIpcHandlers()`, wired `sendToRenderer` relay
- `electron/preload.ts`: Typed `updates` namespace exposed via contextBridge
- `src/shared/types/electron-api.d.ts`: Added `UpdateElectronApiBridge` interface and discriminated union types
- `electron/updateManager.ts`: Added `setStrategy()` method with immutable config update
- Tests cover all channels, authorization, validation, error propagation, cleanup

**Fix round 1 (commit 53ee9679):**
- **C1 fixed:** Removed broken `ipcMain.on('update:state-changed')` relay; tests validate actual `sendToRenderer` path
- **C2 fixed:** Corrected `electron-api.d.ts` imports — removed broken `UpdateElectronApiBridge` import, added `UpdateStateChangedEvent`
- **H1 fixed:** Lazy-init `UpdateManager` after `app.whenReady()`
- **H2 fixed:** Added comment documenting `mainWindow` closure capture
- **H3 fixed:** Discriminated union `{ type: 'state' } | { type: 'progress' }`
- **M1 deferred:** TODO comment for non-atomic `setStrategy` (Task 10)
- **M2/M3/M4 fixed:** Updated tests, replaced WeakMap with module-level var, simplified IpcMain Pick
- **L1/L2/L3 fixed:** Uniform trim, removed redundant `as` assertion and unused import

**Verification:**
- 8/8 updateIpc tests passing
- 73/73 full Electron suite passing
- TypeScript check: no new errors in changed files
- ESLint: clean

**Review findings:**
- Initial review: 2 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW (12 total)
- Fix round 1: All 12 addressed
- Scoped re-review: All findings addressed, no regressions, task may proceed

**Concerns (deferred):**
- Pre-existing typecheck:electron blocked (documented in Task 5)
- Non-atomic setStrategy (M1 deferred to Task 10 with TODO comment)

---

### Task 10: complete (commits 51e65c25..46be3390, review approved)

**Spec compliance:** ✅ — All 13 acceptance criteria met
**Quality:** Approved — 7/7 UI tests + 8/8 IPC tests passing, 68/68 total Electron suite

**Implementation:**
- `UpdatesTab` component with strategy radio, channel select, manual-check button, loading/success/error states
- `update:get-config` and `update:set-channel` IPC handlers with trusted-renderer validation
- Preload bridge and `UpdateElectronApiBridge` type extended with `getConfig()` and `setChannel()`
- i18n keys added (19 in both zh.ts and en.ts)
- Settings page integrated the updates tab (tab 9 of 9)
- 87eb4dde: cache invalidation fix (channel change invalidates cached check result)
- 5fcd958c: Prettier formatting
- 46be3390: stale test description fix (six→eight)

**Verification:**
- 7/7 UpdatesTab tests passing
- 8/8 updateIpc tests passing
- 68/68 total Electron suite passing
- Renderer tsc: clean
- ESLint: clean on all changed files

**Review findings:**
- Initial review: 0 CRITICAL, 0 HIGH, 1 MEDIUM, 5 LOW
- M1 (Settings integration test) — **deferred**: acceptance criterion #11 met (tab integrated); test gap consistent with codebase pattern (no other tab has Settings-level test)
- L1 (stale test description) — **fixed** in 46be3390
- L2 (configError not cleared on success) — **deferred**: minor UX, consistent with codebase pattern
- L3 (unused i18n key) — **deferred**: seed for future migration
- L4 (non-atomic setChannel) — **deferred**: known from Task 9, requires ConfigManager refactor
- L5 (React act warning) — **deferred**: cosmetic, tests pass

**Concerns (deferred):**
- Pre-existing typecheck:electron blocked (documented in Task 5)
- Advanced options (rollback window, check interval, cache clear) deferred per brief
- Non-atomic config read-modify-write (M1 from Task 9)


---

### Task 12: complete (commits ed572d84..aaa7e8c9, review approved)

**Spec compliance:** ✅ — Integration coverage wires real StateManager, ConfigManager, UpdateManager, and LauncherHealthChecker across six upgrade scenarios.
**Quality:** ✅ — Automatic `auto-download` and `auto-install` orchestration is exercised through `checkForUpdates()` rather than manual calls; test isolation is hardened.

**Implementation:**
- Added 14 integration tests covering manual, automatic download/install, rollback, health-check, and persistence flows.
- Added automatic orchestration in `UpdateManager.checkForUpdates()` with reentrance guard.
- Added Node environment directives to Electron main-process update tests to avoid jsdom ESM incompatibility on Node 18.
- Guarded shared test setup for Node environments and removed an unused test fixture.

**Verification:**
- Update suite: **88/88 tests passing** across 6 files.
- Focused review: no CRITICAL or HIGH findings.

**Deferred observation:**
- Concurrent/interleaved update checks are not explicitly covered; current orchestration is guarded for reentrance and the existing serial flow is verified.

---

### Post-task hardening: complete (commits b54c5943, 187fc929)

**Security and lifecycle fixes:** ✅ — Manifest signatures now use RSA-SHA256 verification; artifact URLs are HTTPS + hostname allowlisted; concurrent checks are deduplicated; rollback IPC enforces manual rollback eligibility; cached rollback packages are path/size/hash/signature validated; backend channels are allowlisted.

**Production wiring fixes:** ✅ — Startup health checks are invoked after the main window is created (including retry startup); install state is prepared then persisted before `quitAndInstall()`; Windows NSIS `customInit` executes `.prepare-rollback.bat` before installing the new package.

**Verification:**
- Electron update suite: **91/91 tests passing** across 6 files.
- Backend update tests: **15/15 passing**.
- Renderer TypeScript check: passed.
- ESLint: changed TypeScript files clean; NSIS is outside ESLint configuration.
- `src/components/UpdateDialog.tsx` formatting changes remain unmodified, per user instruction.

**Main/win7 alignment:** `release/win7` does not contain the update subsystem files, so no compatible cherry-pick was applied. Its Python 3.8 dependency boundary remains untouched.

---

### Task 11: complete (commits 42cefc71..b3b87fd0, review approved after fix round 1)

**Spec compliance:** ✅ — All 13 acceptance criteria met
**Quality:** Approved — 15/15 UpdateDialog tests, 65/65 Electron suite, no regressions

**Implementation:**
- `UpdateDialog` component with 4 phases: update-available, downloading, ready-to-install, rollback
- Plain-text release notes rendering with line breaks preserved
- Non-dismissible modal (no backdrop click, no ESC)
- i18n keys added (14 in both zh.ts and en.ts)
- Integrated into `src/App.tsx` as global notification
- Persisted state relay on app startup (did-finish-load)

**Fix round 1 (commit b3b87fd0):**
- **H1 fixed:** Phase 3 "稍后重启" now closes dialog via `dismissedVersion` tracking
- **H2 fixed:** Same version after defer stays hidden; new version re-shows (string equality check)
- **H3 fixed:** All IPC actions wrapped in `runWithGuard()` with try/catch, error display (`role="alert"`), and `isInFlight` dedup
- **M1 fixed:** Focus management via rAF + cleanup (save/restore `document.activeElement`)
- **M2 fixed:** Primary and rollback buttons disabled during `isInFlight`
- **Tests:** 5 new tests covering H1/H2/H3/M2; all `act()` warnings resolved

**Verification:**
- 15/15 UpdateDialog tests passing (was 10/10, added 5 fix-verification tests)
- 65/65 Electron suite passing
- TypeScript: clean
- ESLint: clean on changed files

**Review findings:**
- Initial review: 0 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW
- Fix round 1: All 3 HIGH + 2 MEDIUM addressed
- Scoped re-review: All findings verified, no regressions

**Concerns (deferred):**
- Pre-existing typecheck:electron blocked (documented in Task 5)
- Pre-existing ESLint:unused `configPath` in `electron/tests/updateConfig.test.ts:22`
- M3 (initial state race) — theoretical, not observed in practice
- M4 (unused i18n key `rollbackNotAvailable`) — retained for future use
