/**
 * Electron main process — Sage desktop shell
 *
 * NOTE: ESLint flat config disabled for this file — uses Node.js globals
 * (require/process/console/__dirname) and CommonJS-style require() that the
 * browser-targeted eslint.config.js rejects. main process is Node, not
 * browser, so these are legitimate. If eslint.config.js is later extended
 * with a Node-flavored block for `electron/**`, remove this top-level
 * disable.
 *
 * Phase 1 (2026-06-13): Win7 tech-stack replacement
 * - Replaces Tauri 2.1.1 (which hard-depends on WebView2 = Win10+)
 * - Electron 21.4.4 ships bundled Chromium 106, the last Electron
 *   with official Windows 7 support (Electron 22+ drops Win7/8/8.1)
 *
 * Responsibilities:
 *   1. Spawn FastAPI Python backend (conda env `sage-backend`) on port 8765
 *   2. Wait for backend /health to be ready
 *   3. Create BrowserWindow loading Vite dev URL (dev) or dist/index.html (prod)
 *   4. Bridge IPC invoke/listen between renderer and backend HTTP/SSE
 *   5. Cleanly shut down backend subprocess on app quit
 *
 * Win7 compat flags (Phase 3 will tune further):
 *   - app.disableHardwareAcceleration() (Win7 GPU drivers flaky)
 *   - --no-sandbox (Win7 SUID-less chrome-sandbox)
 *   - --disable-gpu (compositor fallback)
 */
// Logger MUST be the first import — it must be initialized before the GPU
// compat flags below so any throw from `app.disableHardwareAcceleration()`
// or `app.commandLine.appendSwitch(...)` is captured to the NDJSON log file.
//
// NOTE: `electron` is imported FIRST so `app.isPackaged` (used in the
// initial log line below) is resolvable in the compiled CommonJS output.
// TypeScript preserves source order of imports; if `./logger` is required
// before `electron`, the `app.isPackaged` reference throws a TDZ error at
// runtime even though tsc --noEmit is happy.
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import { logger } from './logger';
logger.info('main: process started', {
  pid: process.pid,
  electronVer: process.versions.electron,
  platform: process.platform,
  packaged: app.isPackaged,
});

import { spawn, ChildProcess } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  constants as fsConstants,
  lstatSync,
  existsSync,
  openSync,
  closeSync,
  writeSync,
  readFileSync,
  mkdirSync,
  renameSync,
  unlinkSync,
} from 'node:fs';
import http from 'node:http';
import fetch from 'node-fetch';
import { relayChatStream, relayNdjsonToEvent, WIKI_STREAM_ERROR } from './relay';
import { streamControllers } from './commands';
import { registerSkillsIpc } from './skillsIpc';
import { buildApplicationMenu } from './menu';
import { showStartupFailureDialog } from './showStartupFailureDialog';
import { cleanupOlderThan } from './logRotate';
import { registerLogIpc } from './ipc/logIpc';
import { resolveBackendLaunchCommand } from './backendLauncher';
import { loadBuildManifest, ownsBackend, type BackendHealthEnvelope } from './buildManifest';
import { isCurrentGeneration, type BackendGeneration } from './backendSupervisor';
import { killOrphanedBackendOnPort } from './orphanBackendKiller';
import { createIncrementalUtf8Decoder } from './incrementalUtf8Decoder';
import { BackendNotReadyError, invokeBackend } from './invoke';
import { runDoctorCheck } from './doctor';
import { mainWindow, setMainWindow } from './mainWindow';

const BACKEND_PORT = Number(process.env.PYTHON_BACKEND_PORT ?? 8765);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_HEALTH = `${BACKEND_URL}/health/proof`;
const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged;
const VITE_DEV_URL = process.env.VITE_DEV_SERVER_URL ?? 'http://localhost:1420';
const buildManifest = loadBuildManifest(
  process.resourcesPath ? join(process.resourcesPath, 'build-manifest.json') : '',
  // CRITICAL: guard app.getVersion() for vitest environments where the
  // `electron` module mock (`vi.mock('electron', () => ({ app: { ... } }))`)
  // does not include `getVersion`. Production Electron always provides it,
  // but the test_backend_auto_restart.test.ts suite loads main.ts for
  // module-level side effects (loading buildManifest triggers parseLogPaths,
  // which spawns fs calls that error out in jsdom), so we cannot mock
  // `loadBuildManifest` away cleanly. Optional-chaining + a stable fallback
  // lets tests pass without forking the load path.
  { version: typeof app.getVersion === 'function' ? app.getVersion() : 'unknown' },
);

// A process-wide single-instance lock prevents two Electron supervisors from
// racing over the same backend port and database.
//
// CRITICAL: guard app.requestSingleInstanceLock() for vitest environments
// where the `electron` module mock in test_backend_auto_restart.test.ts
// doesn't provide requestSingleInstanceLock. Production Electron always
// provides it; the vitest mock intentionally exposes only the surface the
// suite actually exercises. Same rationale as the app.getVersion() guard at
// line 84 above.
const gotSingleInstanceLock =
  typeof app.requestSingleInstanceLock === 'function' ? app.requestSingleInstanceLock() : true;
if (!gotSingleInstanceLock) {
  // CRITICAL: short-circuit ALL subsequent initialization, not just app.quit().
  //
  // app.quit() schedules an async shutdown (next-tick); without a hard cutover
  // the rest of this module would still execute on the next tick — building a
  // second BrowserWindow, registering IPC handlers, spawning a second backend
  // on the same port, clashing with the running supervisor. process.exit(0)
  // is the synchronous terminator that prevents the duplicate-state race the
  // previous "app.quit(); (continue)" pattern caused.
  app.quit();
  process.exit(0);
}

// Window dimensions
const DEFAULT_WINDOW_WIDTH = 1280;
const DEFAULT_WINDOW_HEIGHT = 800;
const MIN_WINDOW_WIDTH = 1024;
const MIN_WINDOW_HEIGHT = 640;

// Timeouts (milliseconds)
const BACKEND_HEALTH_TIMEOUT_MS = 30_000;
const BACKEND_SHUTDOWN_TIMEOUT_MS = 3_000;
const HTTP_REQUEST_TIMEOUT_MS = 1_000;

// V8 heap limit (MB) - Win7 compat: cap V8 heap to 2GB so Win7 systems
// with 4GB RAM don't OOM-kill during chat streaming
const V8_MAX_OLD_SPACE_SIZE_MB = 2048;

// Win7 compat: disable GPU + sandbox BEFORE app ready.
// Order matters — these flags must be set before `whenReady()`.
//
// Why each flag:
//   - disableHardwareAcceleration: Win7 GPU drivers are flaky under V8/Blink;
//     falling back to software compositing is more reliable on legacy GPUs.
//   - --no-sandbox: Win7 lacks the SUID chrome-sandbox helper (chmod 4755
//     chrome-sandbox), so Electron refuses to launch sandboxed.
//   - --disable-gpu: forces CPU compositor path; Win7 D3D11 drivers
//     often crash Electron's GPU process.
//   - --disable-software-rasterizer: opt out of Skia software rasterizer
//     to avoid Win7 GPU driver DLL conflicts.
//   - --in-process-gpu: keep GPU in main process (Win7 multi-process model
//     is more crash-prone than single-process).
//   - --disable-features=VizDisplayCompositor: skip Chromium's Viz
//     display compositor; Win7 D3D11 not feature-complete.
//   - --js-flags=--max-old-space-size=${V8_MAX_OLD_SPACE_SIZE_MB}: cap V8 heap to 2GB so Win7
//     systems with 4GB RAM don't OOM-kill during chat streaming.
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');
app.commandLine.appendSwitch('in-process-gpu');
app.commandLine.appendSwitch('disable-features', 'VizDisplayCompositor');
app.commandLine.appendSwitch('js-flags', `--max-old-space-size=${V8_MAX_OLD_SPACE_SIZE_MB}`);

let backendProc: ChildProcess | null = null;
let backendGeneration = 0;
let currentBackend: BackendGeneration | null = null;
let backendLifecycle: 'idle' | 'starting' | 'ready' | 'stopping' = 'idle';
let backendAuthToken: string | null = null;

// PR-B: backend auto-restart state
//
// When the backend subprocess exits unexpectedly (crash, OOM-kill, broken
// installer re-spawn) we retry up to MAX_RESTART_ATTEMPTS times with
// exponential backoff (RESTART_BASE_DELAY_MS * 2^n, capped at
// RESTART_MAX_DELAY_MS) so a transient conda hiccup doesn't white-screen
// the app. After MAX_RESTART_ATTEMPTS exhausted, the renderer is told via
// `backend:disconnected { attempt: -1 }` to show a "please restart Sage"
// banner.
//
// `appIsQuitting` is set true in `before-quit` so the user-initiated quit
// path doesn't trigger a fresh restart loop.
let restartCount = 0;
let restartTimer: NodeJS.Timeout | null = null;
let appIsQuitting = false;
const MAX_RESTART_ATTEMPTS = 3;
const RESTART_BASE_DELAY_MS = 1000;
const RESTART_MAX_DELAY_MS = 8000;

// Set by spawnBackend() when the resolver reports a broken installer, so the
// startup-failure path in app.whenReady() can SKIP its own dialog (which
// would otherwise show a misleading "port 8765 occupied / conda not installed"
// message 30s after the user already saw the accurate broken-installer dialog).
//
// Without this sentinel the user would see two stacked modal dialogs: a
// correct one immediately, then a misleading one ~30s later.
let reportedBrokenInstaller = false;

/**
 * Locate and spawn the Python interpreter that runs the FastAPI backend.
 *
 * Decision logic lives in `electron/backendLauncher.ts` (pure, unit-tested).
 * This wrapper:
 *   1. Computes SAGE_DB_PATH and SAGE_USER_DATA_DIR (uses electron's userData
 *      when packaged).
 *   2. Calls the resolver.
 *   3. spawns the returned cmd, OR — if the resolver says the installer is
 *      broken (bundled Python missing, macOS unsupported, etc.) — surfaces a
 *      user-friendly error dialog and returns a no-op stub process that exits
 *      immediately.
 *
 * Why "broken installer" → dialog instead of "spawn conda as fallback":
 *   The previous implementation fell back to `spawn('conda', ...)` when
 *   bundled Python was missing. End-user machines have no conda, so this
 *   produced an opaque "spawn conda ENOENT" JavaScript crash in the main
 *   process — the actual cause (missing bundled Python) was hidden.
 *   We now refuse the fallback in packaged mode and tell the user what to do.
 */
function spawnBackend(): ChildProcess {
  // Resolve SAGE_DB_PATH and SAGE_USER_DATA_DIR once so both packaged and
  // dev spawn paths share them. Backend prefers these env vars; falls back to:
  //   - Dev (running from repo): <repo>/data/* (project-local so developers
  //     see their existing session history during `npm run electron:dev`).
  //   - Packaged app: <userData>/* (per-user writable location, ALWAYS —
  //     critical for Win installs to C:\Program Files\Sage which is a
  //     system-protected directory and rejects writes from non-admin users).
  // SAGE_DB_PATH / SAGE_USER_DATA_DIR env vars always win (for CI / override).
  const sageDbPath =
    process.env.SAGE_DB_PATH ??
    (app.isPackaged
      ? join(app.getPath('userData'), 'sage.db')
      : join(process.cwd(), 'data', 'sage.db'));
  const sageUserDataDir =
    process.env.SAGE_USER_DATA_DIR ??
    (app.isPackaged ? app.getPath('userData') : join(process.cwd(), 'data'));

  const plan = resolveBackendLaunchCommand({
    env: process.env,
    resourcesPath: process.resourcesPath,
    platform: process.platform,
    isPackaged: app.isPackaged,
    sageDbPath,
    sageUserDataDir,
    port: BACKEND_PORT,
  });

  if (plan.kind === 'broken-installer') {
    logger.error('main: broken installer — bundled Python missing', {
      reason: plan.reason,
      detail: plan.detail,
    });
    // Mark so the health-timeout branch in app.whenReady() suppresses its
    // own (misleading) "port occupied / conda" dialog 30s later. Without
    // this, the user sees two stacked modal dialogs about the same problem.
    reportedBrokenInstaller = true;
    void showStartupFailureDialog({
      reason: plan.title,
      detail: plan.detail,
    });
    // Return a no-op stub proc that exits immediately so the rest of the
    // startup flow (health probe → timeout) still works predictably.
    return spawnStubProcess(plan.reason);
  }

  // plan.kind === 'spawn' — happy path
  if (backendProc && backendLifecycle !== 'idle') {
    return backendProc;
  }
  const generation = ++backendGeneration;
  const ownershipToken = randomUUID();
  backendAuthToken = process.env.SAGE_LOCAL_AUTH_TOKEN ?? randomBytes(32).toString('base64url');
  currentBackend = { generation, pid: -1, ownershipToken };
  backendLifecycle = 'starting';
  // Task 0 review round 1, finding #6: tell the renderer the new lifecycle
  // state so BackendStatusBanner can show "starting…" before the first
  // health probe lands.
  mainWindow?.webContents.send('backend:starting', { generation });

  // ── Orphan cleanup (Windows only) ──────────────────────────────────────
  // A previous Electron main process may have crashed without running
  // shutdownBackend(), leaving a Python backend still listening on
  // BACKEND_PORT. On Windows (SO_REUSEADDR) both old and new backends
  // would bind the same port, and HTTP requests from the frontend may
  // be routed to the stale process whose DB state is inconsistent —
  // causing 500 errors and a white screen. Kill any such orphan before
  // spawning our own backend. No-op on non-Windows platforms.
  const killResult = killOrphanedBackendOnPort({
    port: BACKEND_PORT,
    platform: process.platform,
    selfPid: process.pid,
  });
  if (killResult.kind === 'killed') {
    logger.info('main: killed orphaned backend process(es) on port', {
      port: BACKEND_PORT,
      pids: killResult.pids,
    });
  }

  const proc = spawn(plan.command, plan.args, {
    cwd: plan.cwd,
    env: {
      ...process.env,
      ...plan.env,
      ...plan.extraEnv,
      SAGE_BUILD_ID: buildManifest.buildId,
      SAGE_BUILD_COMMIT: buildManifest.commit,
      SAGE_BUILD_BRANCH: buildManifest.branch,
      SAGE_BUILD_VERSION: buildManifest.version,
      SAGE_ELECTRON_VERSION: buildManifest.electronVersion,
      SAGE_PYTHON_VERSION: buildManifest.pythonVersion,
      SAGE_BACKEND_GENERATION: String(generation),
      SAGE_BACKEND_OWNERSHIP_TOKEN: ownershipToken,
      SAGE_LOCAL_AUTH_TOKEN: backendAuthToken,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  currentBackend = { generation, pid: proc.pid ?? -1, ownershipToken };

  // One incremental UTF-8 decoder per stream, scoped to this child process so
  // any incomplete multi-byte sequence that arrived in the final write before
  // 'exit' is preserved (not silently dropped as U+FFFD).
  const stdoutDecoder = createIncrementalUtf8Decoder();
  const stderrDecoder = createIncrementalUtf8Decoder();

  logger.info('main: backend spawned', {
    reason: plan.reason,
    cmd: plan.cmd,
    args: plan.args,
  });

  proc.stdout?.on('data', (b) =>
    logger.debug('backend: stdout', { line: stdoutDecoder.push(b).trim() }),
  );
  proc.stderr?.on('data', (b) =>
    logger.error('backend: stderr', { line: stderrDecoder.push(b).trim() }),
  );
  proc.on('exit', (code) => {
    if (!isCurrentGeneration({ generation, pid: proc.pid ?? -1, ownershipToken }, currentBackend)) {
      logger.debug('main: stale backend exit ignored', { generation, pid: proc.pid });
      return;
    }
    logger.info('main: backend exited', { code, generation, pid: proc.pid });
    backendProc = null;
    currentBackend = null;
    backendLifecycle = 'idle';
    // Flush the incremental UTF-8 decoders so any buffered bytes from the
    // child's final write are surfaced to the log; with stream:true TextDecoder
    // would otherwise drop them silently.
    stdoutDecoder.close();
    stderrDecoder.close();
    if (!appIsQuitting) {
      scheduleBackendRestart();
    }
  });
  // Without an 'error' listener, Node treats spawn-time failures (binary
  // exists but is not executable, ACL block, AV lock, ENOEXEC) as uncaught
  // exceptions and crashes the Electron main process — exactly the failure
  // mode PR #130 was meant to fix. PR #130 review flagged this as issue #10.
  proc.on('error', (err) => {
    if (!isCurrentGeneration({ generation, pid: proc.pid ?? -1, ownershipToken }, currentBackend)) {
      logger.debug('main: stale backend spawn error ignored', { generation, pid: proc.pid });
      return;
    }
    logger.error('main: backend spawn error', {
      reason: plan.reason,
      cmd: plan.cmd,
      err: String(err),
    });
    backendProc = null;
    currentBackend = null;
    backendLifecycle = 'idle';
  });
  return proc;
}

/**
 * Stand-in subprocess used when the resolver reports a broken installer.
 *
 * We can't return `null` (caller typed as ChildProcess) and we don't want
 * to leave `backendProc = null` without a process so health polling can run
 * predictably. Spawning `process.execPath` with `--version` is portable
 * and exits within milliseconds — the subsequent `waitForBackend()` will
 * simply time out and the user will see the broken-installer dialog.
 */
function spawnStubProcess(reason: string): ChildProcess {
  const stub = spawn(process.execPath, ['--version'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  // Use the same incremental UTF-8 decoder as spawnBackend for consistency.
  const stdoutDecoder = createIncrementalUtf8Decoder();
  const stderrDecoder = createIncrementalUtf8Decoder();
  stub.stdout?.on('data', (b) =>
    logger.debug('main: stub proc stdout', {
      reason,
      line: stdoutDecoder.push(b).trim(),
    }),
  );
  stub.stderr?.on('data', (b) =>
    logger.error('main: stub proc stderr', {
      reason,
      line: stderrDecoder.push(b).trim(),
    }),
  );
  stub.on('exit', (code) => {
    logger.info('main: stub proc exited', { reason, code });
    stdoutDecoder.close();
    stderrDecoder.close();
    backendProc = null;
  });
  // Same rationale as spawnBackend's `'error'` handler above — stub may fail
  // to start (e.g. process.execPath is locked) and we don't want an uncaught
  // exception to bubble out of the Electron main process.
  stub.on('error', (err) => {
    logger.error('main: stub proc error', { reason, err: String(err) });
    backendProc = null;
  });
  return stub;
}

/**
 * PR-B: backend 进程异常退出时,指数退避自动重 spawn,最多 3 次。
 *
 * 退避序列 1s/2s/4s。第 3 次后永久失败,通过 IPC 通知 renderer 显示
 * 「请重启 Sage」横幅。用户在 app quit 触发的 exit 不重试。
 *
 * Race-fix (Task 0 review round 1, finding #4): the respawn timer now AWAITS
 * `shutdownBackend()` (which awaits child exit + port release) before
 * calling `spawnBackend()`. Without this, the new spawn could race the OS
 * releasing the listening socket and hit EADDRINUSE → white screen.
 *
 * Exported so unit tests can drive restart counter + IPC notifications
 * without spawning a real Electron process.
 */
export function scheduleBackendRestart(): void {
  if (appIsQuitting || restartTimer) return;
  if (restartCount >= MAX_RESTART_ATTEMPTS) {
    logger.error('main: backend restart exhausted', { attempts: restartCount });
    mainWindow?.webContents.send('backend:disconnected', { attempt: -1 });
    return;
  }
  restartCount++;
  const delay = Math.min(RESTART_BASE_DELAY_MS * 2 ** (restartCount - 1), RESTART_MAX_DELAY_MS);
  logger.warn('main: scheduling backend restart', {
    attempt: restartCount,
    delayMs: delay,
  });
  mainWindow?.webContents.send('backend:disconnected', { attempt: restartCount });
  restartTimer = setTimeout(() => {
    restartTimer = null;
    if (appIsQuitting || backendProc || currentBackend || backendLifecycle !== 'idle') return;
    // AWAIT prior shutdown (no-op if backendProc is null) so the new spawn
    // doesn't collide with a still-releasing listening socket.
    void shutdownBackend().then(() => {
      if (appIsQuitting || backendProc || currentBackend || backendLifecycle !== 'idle') return;
      backendProc = spawnBackend();
      const expectedBackend = currentBackend;
      waitForBackend().then((ready) => {
        if (!isCurrentGeneration(expectedBackend, currentBackend)) return;
        if (ready) {
          restartCount = 0;
          mainWindow?.webContents.send('backend:reconnected', {});
        }
      });
    });
  }, delay);
  restartTimer.unref();
}

/**
 * Poll /health until backend responds 200, with timeout.
 * Backend startup usually <2s; cap at 30s to surface real failures fast.
 *
 * Race-fix (Task 0 review round 1, finding #3): after `ownsBackend` matches
 * we MUST recheck the live child/generation/PID/token and verify the port is
 * still bound by the same PID before publishing `ready`. Otherwise, if the
 * backend we just spawned exits between the health-poll and the lifecycle
 * transition, we'd hand a stale `ready` flag to the renderer that points at
 * a dead process.
 */
async function waitForBackend(timeoutMs = BACKEND_HEALTH_TIMEOUT_MS): Promise<boolean> {
  const expectedBackend = currentBackend;
  if (!expectedBackend || backendLifecycle !== 'starting') return false;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isCurrentGeneration(expectedBackend, currentBackend) || appIsQuitting) return false;
    try {
      const health = await new Promise<unknown>((resolve) => {
        const req = http.get(
          BACKEND_HEALTH,
          {
            headers: { 'X-Sage-Backend-Ownership': expectedBackend.ownershipToken },
          },
          (res) => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', (chunk: string) => {
              body += chunk;
            });
            res.on('end', () => {
              if (res.statusCode !== 200) {
                resolve(null);
                return;
              }
              try {
                resolve(JSON.parse(body) as unknown);
              } catch {
                resolve(null);
              }
            });
            res.resume();
          },
        );
        req.on('error', () => resolve(null));
        req.setTimeout(HTTP_REQUEST_TIMEOUT_MS, () => {
          req.destroy();
          resolve(null);
        });
      });
      if (ownsBackend(health as Partial<BackendHealthEnvelope>, expectedBackend, buildManifest)) {
        // ── Race-fix recheck ─────────────────────────────────────────────
        // 1. Generation/PID/token still match the live supervisor state.
        // 2. The ChildProcess is still alive and not exited.
        // 3. The port is still bound by the same PID (a sibling fresh
        //    backend could have grabbed the port between the HTTP probe
        //    returning 200 and this recheck; the ownershipToken check above
        //    rules that out, but we still want a structural assertion that
        //    the socket we hit belongs to the expected PID).
        if (!isCurrentGeneration(expectedBackend, currentBackend)) return false;
        if (!backendProc || backendProc.exitCode !== null || backendProc.signalCode !== null) {
          return false;
        }
        if (!(await isPortStillBoundByPid(BACKEND_PORT, expectedBackend.pid, 200))) {
          return false;
        }
        backendLifecycle = 'ready';
        // Task 0 review round 1, finding #6: tell the renderer the backend
        // is ready so BackendStatusBanner can clear the "starting…" state
        // (or never show it, if the spawn-to-ready window was sub-frame).
        mainWindow?.webContents.send('backend:ready', { generation: expectedBackend.generation });
        return true;
      }
    } catch {
      /* transient connection or malformed health payload */
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

/**
 * Verify that `port` on loopback is still bound by `expectedPid` within
 * `timeoutMs`. Returns true if we can confirm the binding still belongs to
 * the expected PID, false if the socket is missing, owned by a different PID,
 * or we couldn't determine within the timeout. Defensive — used by the
 * race-fix recheck in `waitForBackend` to catch the case where the backend
 * we just probed has been swapped out under us.
 *
 * Linux/macOS: parse `lsof -iTCP:<port> -sTCP:LISTEN -F p`.
 * Windows: parse `netstat -ano` filtered to LISTENING rows whose local
 * address ends with `:<port>`.
 */
async function isPortStillBoundByPid(
  port: number,
  expectedPid: number,
  timeoutMs: number,
): Promise<boolean> {
  if (expectedPid <= 0) return false;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const pids: number[] = [];
    try {
      if (process.platform === 'win32') {
        const { execFileSync } = await import('node:child_process');
        const out = execFileSync('netstat', ['-ano', '-p', 'TCP'], {
          encoding: 'utf8',
          timeout: 500,
        });
        const portSuffix = `:${port}`;
        for (const raw of out.split(/\r?\n/)) {
          const line = raw.trim();
          if (!line.startsWith('TCP')) continue;
          const cols = line.split(/\s+/);
          if (cols.length < 5) continue;
          const localAddr = cols[1] ?? '';
          const state = cols[3] ?? '';
          const pidStr = cols[4] ?? '';
          if (state !== 'LISTENING') continue;
          if (!localAddr.endsWith(portSuffix)) continue;
          const pid = Number.parseInt(pidStr, 10);
          if (Number.isFinite(pid) && pid > 0) pids.push(pid);
        }
      } else {
        const { execFileSync } = await import('node:child_process');
        // `-sTCP:LISTEN` keeps noise low; `-F p` prints machine-parseable PIDs.
        const out = execFileSync('lsof', ['-iTCP:' + String(port), '-sTCP:LISTEN', '-F', 'p'], {
          encoding: 'utf8',
          timeout: 500,
        });
        for (const raw of out.split('\n')) {
          const line = raw.trim();
          if (!line.startsWith('p')) continue;
          const pid = Number.parseInt(line.slice(1), 10);
          if (Number.isFinite(pid) && pid > 0) pids.push(pid);
        }
      }
    } catch {
      /* tool missing, permission denied, or transient — fall through to retry */
    }
    if (pids.length > 0 && pids.includes(expectedPid)) return true;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return false;
}

/**
 * Forward invoke(cmd, args) to FastAPI backend HTTP endpoint.
 * Command-to-route mapping mirrors the original Tauri command surface.
 *
 * I2: 后端 /chat/stream 拆成 create + attach。create 端点(agent_chat_stream)
 * 直接返回 {streamId: '...'} JSON,无需读 NDJSON 首行。attach 端点由
 * ipcMain.handle('sage:listen') 触发 relayChatStream,GET 拉事件。
 *
 * I1 fix (待清理): 老的 pendingChatArgs TTL 缓存在 I2 后不再需要(后端持有 args,
 * streamId 唯一即可定位)。本 PR 暂时保留该类供 review,下一 PR 删除。
 *
 * `invokeBackend` 本身已抽到 electron/invoke.ts(用 node-fetch 替代全局 fetch,
 * 详见该文件头注)。本文件只保留 IPC handler 注册 + Electron 生命周期。
 */

function createMainWindow(): void {
  // Platform-specific titlebar configuration:
  // - macOS: hide traffic light area, custom titlebar from y=28
  // - Windows/Linux: frameless window with custom titlebar
  const isMac = process.platform === 'darwin';
  const titleBarOptions = isMac
    ? { titleBarStyle: 'hidden' as const, trafficLightPosition: { x: 8, y: 8 } }
    : { frame: false };

  const win = new BrowserWindow({
    width: DEFAULT_WINDOW_WIDTH,
    height: DEFAULT_WINDOW_HEIGHT,
    minWidth: MIN_WINDOW_WIDTH,
    minHeight: MIN_WINDOW_HEIGHT,
    title: 'Sage',
    icon: join(__dirname, '..', 'build', 'icon.ico'),
    ...titleBarOptions,
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // Phase 3: keep false for Win7 compat (sandbox needs SUID)
    },
  });
  setMainWindow(win);

  // Open external links in OS browser, not in-app
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url).catch(() => undefined);
    return { action: 'deny' };
  });

  if (isDev) {
    win.loadURL(VITE_DEV_URL).catch(async (e) => {
      logger.error('main: loadURL failed', { url: VITE_DEV_URL, err: e.message });
      await showStartupFailureDialog({
        reason: '加载前端开发服务失败',
        detail: `URL: ${VITE_DEV_URL}\n错误: ${e.message}`,
      });
    });
    win.webContents.openDevTools({ mode: 'detach' });
  } else {
    // tsconfig.electron.json uses rootDirs: [electron, src], so the compiled
    // main.js lives at dist-electron/electron/main.js (one extra directory level
    // vs the legacy rootDir: electron setup). Go up two levels to reach dist/.
    const indexHtml = join(__dirname, '..', '..', 'dist', 'index.html');
    win.loadFile(indexHtml).catch(async (e) => {
      logger.error('main: loadFile failed', { path: indexHtml, err: e.message });
      await showStartupFailureDialog({
        reason: '加载前端资源失败',
        detail: `路径: ${indexHtml}\n错误: ${e.message}`,
      });
    });
    // Diagnostic: log when page finishes loading (or fails)
    win.webContents.on('did-finish-load', () => {
      logger.info('main: frontend did-finish-load', { url: win.webContents.getURL() });
      // Diagnostic: check if React root is mounted after page loads
      win.webContents
        .executeJavaScript(
          `
          (function() {
            const root = document.getElementById('root');
            const body = document.body;
            const hasElectronAPI = typeof window.electronAPI !== 'undefined';
            const apiKeys = hasElectronAPI ? Object.keys(window.electronAPI || {}) : [];
            return {
              hasRoot: !!root,
              rootChildren: root?.children.length || 0,
              rootInnerHTML: root?.innerHTML?.substring(0, 500) || '',
              bodyInnerHTML: body?.innerHTML?.substring(0, 500) || '',
              hasSidebar: !!document.querySelector('[class*="sidebar" i], aside, nav'),
              hasLayout: !!document.querySelector('[class*="layout" i]'),
              allElements: document.querySelectorAll('*').length,
              hasElectronAPI,
              apiKeys,
              scripts: Array.from(document.scripts).map(s => s.src || s.textContent?.substring(0, 100) || ''),
              title: document.title,
            };
          })()
        `,
        )
        .then((result) => {
          logger.info('main: frontend React root check', result);
        })
        .catch((e) => {
          logger.error('main: failed to check React root', { error: e.message });
        });
    });
    win.webContents.on('did-fail-load', (_event, errorCode, errorDescription) => {
      logger.error('main: frontend did-fail-load', { errorCode, errorDescription });
    });
    // Diagnostic: capture console messages (JS errors, warnings, logs)
    win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
      const logLevel =
        level === 0 ? 'debug' : level === 1 ? 'info' : level === 2 ? 'warn' : 'error';
      logger[logLevel]('main: frontend console', { level, message, line, sourceId });
    });
    // Diagnostic: capture page crashes (using non-deprecated render-process-gone)
    win.webContents.on('render-process-gone', (_event, details) => {
      logger.error('main: frontend render-process-gone', {
        reason: details.reason,
        exitCode: details.exitCode,
      });
    });
    win.webContents.on('unresponsive', () => {
      logger.error('main: frontend unresponsive');
    });
  }

  win.on('closed', () => {
    setMainWindow(null);
  });
}

function registerIpcHandlers(): void {
  ipcMain.handle(
    'sage:invoke',
    async (_evt, payload: { cmd: string; args?: Record<string, unknown> }) => {
      // Streaming commands need their own dispatcher branch — they
      // fire-and-forget the relay and return { streamId } immediately so
      // the renderer can subscribe + unlisten via the existing IPC
      // channels without waiting for the backend to complete.
      // Streaming commands also get the readiness gate — the relay opens
      // an HTTP fetch to the backend, so it's pointless to start one
      // before lifecycle === 'ready'.
      // Task 0 review round 1, finding #6: gate ALL initial invokes on
      // backend readiness. Without this, the renderer hits ECONNREFUSED
      // on cold start (backend takes ~2s to come up after Electron whenReady)
      // and the BackendStatusBanner shows "reconnecting" while the user is
      // staring at a half-loaded UI. We throw BackendNotReadyError which
      // desktopInvoke.ts surfaces verbatim; the banner listens to the
      // 'backend:disconnected' event for the auto-reconnecting banner.
      if (backendLifecycle !== 'ready') {
        logger.warn('ipc: invoke blocked — backend not ready', {
          cmd: payload.cmd,
          lifecycle: backendLifecycle,
        });
        throw new BackendNotReadyError();
      }
      if (payload.cmd === 'wiki_chat_stream') {
        return startWikiChatStream(_evt.sender, payload.args ?? {}, BACKEND_URL);
      }
      if (payload.cmd === 'wiki_ingest_stream') {
        return startWikiIngestStream(_evt.sender, payload.args ?? {}, BACKEND_URL);
      }
      try {
        return await invokeBackend(
          payload.cmd,
          payload.args ?? {},
          BACKEND_URL,
          backendAuthToken ?? undefined,
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        logger.error('ipc: invoke failed', { cmd: payload.cmd, err: msg });
        throw new Error(msg);
      }
    },
  );

  ipcMain.handle(
    'sage:backend-request',
    async (
      evt,
      request: {
        method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
        path: string;
        headers?: Record<string, string>;
        body?: unknown;
        timeoutMs?: number;
      },
    ) => {
      if (!isTrustedRenderer(evt.sender)) throw new Error('未授权的窗口请求');
      if (isDemoProcess()) throw new Error('演示模式不支持该后端操作');
      // Raw requests use the same lifecycle gate as sage:invoke. In particular,
      // never probe a stale port with the previous generation's capability.
      if (backendLifecycle !== 'ready') {
        logger.warn('ipc: backend-request blocked — backend not ready', {
          lifecycle: backendLifecycle,
        });
        throw new BackendNotReadyError();
      }
      if (!request || typeof request.path !== 'string') {
        throw new Error('无效的后端请求路径');
      }
      let backendPath: string;
      try {
        const parsed = new URL(request.path, BACKEND_URL);
        const backendOrigin = new URL(BACKEND_URL);
        const isLoopbackBackendOrigin =
          (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost') &&
          parsed.port === backendOrigin.port;
        if (
          (!isLoopbackBackendOrigin && parsed.origin !== BACKEND_URL) ||
          !parsed.pathname.startsWith('/api/v1/')
        ) {
          throw new Error('outside backend API');
        }
        backendPath = `${parsed.pathname}${parsed.search}`;
      } catch {
        throw new Error('无效的后端请求路径');
      }
      const headers: Record<string, string> = {
        ...(request.headers ?? {}),
        'X-Sage-Local-Authorization': `Bearer ${backendAuthToken ?? ''}`,
      };
      const controller = new AbortController();
      const timeoutMs =
        typeof request.timeoutMs === 'number' && Number.isFinite(request.timeoutMs)
          ? Math.min(Math.max(request.timeoutMs, 1), 60_000)
          : undefined;
      const timeout =
        timeoutMs === undefined ? undefined : setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(`${BACKEND_URL}${backendPath}`, {
          method: request.method ?? 'GET',
          headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          signal: controller.signal,
        });
        if (!response.ok) {
          const text = await response.text().catch(() => '');
          throw new Error(`Backend request failed: ${response.status} ${text}`);
        }
        return response.json();
      } finally {
        if (timeout !== undefined) clearTimeout(timeout);
      }
    },
  );

  // listen(event) → subscribe to backend event stream, forward each event
  // payload to renderer via webContents.send('sage:event:${event}', payload).
  //
  // Phase 2 implementation: handles dynamic chat-stream-{streamId} events by
  // opening a streaming fetch to backend /chat/stream/{streamId} endpoint
  // and parsing NDJSON lines. Each line → webContents.send. Subscriptions
  // are tracked in eventSubscriptions Map; unlisten() aborts the fetch.
  const eventSubscriptions = new Map<string, AbortController>();

  ipcMain.handle(
    'sage:listen',
    async (evt, payload: { event: string }): Promise<{ ok: true; event: string }> => {
      const { event } = payload;
      const senderWebContents = evt.sender;
      logger.debug('ipc: listen subscribe', { event });

      // If already subscribed (e.g., React StrictMode double-mount), return early.
      if (eventSubscriptions.has(event)) {
        return { ok: true, event };
      }

      // chat-stream-{streamId} dynamic events: relay backend NDJSON
      const chatStreamMatch = event.match(/^chat-stream-(.+)$/);
      if (chatStreamMatch) {
        const streamId = chatStreamMatch[1];
        const abort = new AbortController();
        eventSubscriptions.set(event, abort);
        // I2: 直接用 streamId attach 到后端已有流 — 不再需要 pendingChatArgs
        // 缓存 args(后端持有,前端只关心 streamId)
        relayChatStream(
          senderWebContents,
          event,
          streamId,
          BACKEND_URL,
          abort.signal,
          backendAuthToken ?? undefined,
        ).catch((e) => {
          if (e instanceof Error && e.name !== 'AbortError') {
            logger.error('ipc: relay error', { event, err: e.message });
          }
        });
        return { ok: true, event };
      }

      // Unknown event: log + no-op (frontend listen() Promise still resolves)
      logger.warn('ipc: unknown event', { event });
      return { ok: true, event };
    },
  );

  ipcMain.handle(
    'sage:unlisten',
    async (_evt, payload: { event: string; streamId?: string }): Promise<{ ok: true }> => {
      const { event, streamId } = payload;
      // Streaming commands: abort the in-flight fetch so the backend
      // stops producing NDJSON. The relay's finally{} block will
      // streamControllers.delete on its own; we delete eagerly here so a
      // re-subscribe with the same id (e.g. after React StrictMode
      // double-mount) gets a fresh controller.
      if (streamId) {
        const controller = streamControllers.get(streamId);
        if (controller) {
          controller.abort();
          streamControllers.delete(streamId);
          logger.debug('ipc: unlisten aborted stream', { streamId });
        }
      }
      const abort = eventSubscriptions.get(event);
      if (abort) {
        abort.abort();
        eventSubscriptions.delete(event);
        logger.debug('ipc: unlisten aborted', { event });
      }
      return { ok: true };
    },
  );

  // ─── Task 6: memory SSE relay ───────────────────────────────────────────
  // Backend exposes GET /api/v1/memory/events (text/event-stream, 15s
  // heartbeat). The renderer cannot reach the backend HTTP port directly
  // (contextIsolation + no nodeIntegration), so main opens an EventSource
  // per window and re-emits each payload to the renderer over
  // `sage:memory:event`. `eventsource` package (not the Node global — even
  // Node 25 lacks it, and Electron 21 embeds Node 16) is used deliberately.
  const memoryEventSources = new Map<number, EventSource>();

  ipcMain.handle('sage:memory:subscribe', (evt) => {
    const sender = evt.sender;
    // Idempotent: React StrictMode double-mount calls subscribe twice; a
    // second call while a connection exists is a no-op (unsubscribe is the
    // only way to close it).
    if (memoryEventSources.has(sender.id)) {
      return { subscribed: true };
    }
    let es: EventSource;
    try {
      es = new EventSource(`${BACKEND_URL}/api/v1/memory/events`);
    } catch (e) {
      // Guard: if the EventSource implementation cannot even construct here
      // (e.g. a future package upgrade that again requires `globalThis.fetch`
      // which Electron 21 main / Node 16 lacks), surface it so the renderer's
      // preload can report SSE-unavailable and the Memory page falls back to
      // polling instead of silently dead-airing.
      logger.error('memory SSE construction failed', { err: String(e) });
      return { subscribed: false, error: String(e) };
    }
    es.onmessage = (msg) => {
      if (!sender.isDestroyed()) {
        sender.send('sage:memory:event', msg.data);
      }
    };
    es.onerror = (err) => {
      logger.error('memory SSE error', { err: String(err) });
      // Don't close — EventSource auto-reconnects on transient failures.
    };
    // Safety net: if the window dies without calling unsubscribe, drop the
    // connection instead of leaking it until app quit.
    sender.once('destroyed', () => {
      const live = memoryEventSources.get(sender.id);
      if (live) {
        live.close();
        memoryEventSources.delete(sender.id);
      }
    });
    memoryEventSources.set(sender.id, es);
    return { subscribed: true };
  });

  ipcMain.handle('sage:memory:unsubscribe', (evt) => {
    const es = memoryEventSources.get(evt.sender.id);
    if (es) {
      es.close();
      memoryEventSources.delete(evt.sender.id);
    }
    return { unsubscribed: true };
  });

  // ─── Phase 5: Window controls IPC handlers ─────────────────────────────
  // These handlers back the custom titlebar buttons (minimize/maximize/close)
  // and page capture for feedback screenshots.

  /** Helper: get the BrowserWindow that sent the IPC event. */
  function getSenderWindow(evt: Electron.IpcMainInvokeEvent): BrowserWindow | null {
    return BrowserWindow.fromWebContents(evt.sender);
  }

  ipcMain.handle('sage:window-controls:minimize', (evt) => {
    const win = getSenderWindow(evt);
    win?.minimize();
  });

  ipcMain.handle('sage:window-controls:toggle-maximize', (evt) => {
    const win = getSenderWindow(evt);
    if (!win) return;
    if (win.isMaximized()) {
      win.unmaximize();
    } else {
      win.maximize();
    }
  });

  ipcMain.handle('sage:window-controls:close', (evt) => {
    const win = getSenderWindow(evt);
    win?.close();
  });

  ipcMain.handle('sage:window-controls:is-maximized', (evt) => {
    const win = getSenderWindow(evt);
    return win?.isMaximized() ?? false;
  });

  ipcMain.handle('sage:window-controls:capture-page', async (evt) => {
    const win = getSenderWindow(evt);
    if (!win) throw new Error('No sender window');
    const image = await win.capturePage();
    // Return base64 PNG (no data URI prefix)
    return image.toPNG().toString('base64');
  });

  // Folder picker for LLM Wiki project create/open (added 2026-06-27)
  ipcMain.handle(
    'sage:dialog:select-directory',
    async (evt, opts: { intent: 'create' | 'open'; defaultPath?: string }) => {
      const win = BrowserWindow.fromWebContents(evt.sender);
      const properties: ('openDirectory' | 'createDirectory')[] = ['openDirectory'];
      if (opts?.intent === 'create') properties.push('createDirectory');
      const result = await dialog.showOpenDialog(win ?? undefined!, {
        properties,
        defaultPath: opts?.defaultPath,
        title: opts?.intent === 'create' ? '选择要创建的项目目录' : '选择要打开的项目目录',
        buttonLabel: opts?.intent === 'create' ? '在此创建' : '打开',
      });
      if (result.canceled || result.filePaths.length === 0) return null;
      return result.filePaths[0];
    },
  );

  // ─── PR-C: Skills load-new IPC (rescan + import) ─────────────────────
  // Three channels back the Skills page buttons:
  //   skills:pick-files → native multi-select dialog
  //   skills:rescan     → POST /api/v1/skills/rescan
  //   skills:import     → POST /api/v1/skills/import (multipart)
  registerSkillsIpc(
    (channel, handler) => {
      ipcMain.handle(channel, async (evt, ...args: unknown[]) => {
        if (!isTrustedRenderer(evt.sender)) throw new Error('未授权的窗口请求');
        if (isDemoProcess()) throw new Error('演示模式不支持该后端操作');
        return handler(evt, ...args);
      });
    },
    () => backendAuthToken ?? undefined,
  );

  // Phase 1.3 (2026-07-16): Office document IPC handlers.
  //   office:pick-file   → native open dialog filtered by doc type
  //   office:save-dialog → native save dialog
  // The 5 office_* HTTP routes are auto-routed via COMMAND_ROUTES in commands.ts.
  registerOfficeIpc((channel, handler) => {
    ipcMain.handle(channel, async (evt, ...args: unknown[]) => {
      if (!isTrustedRenderer(evt.sender)) throw new Error('未授权的窗口请求');
      if (isDemoProcess()) throw new Error('演示模式不支持该后端操作');
      return handler(evt, ...args);
    });
  });

  // PR: log IPC — write renderer-side logs through the main process logger
  // so they share the same NDJSON sink + log rotate.
  registerLogIpc(ipcMain);
}

/**
 * Start a wiki chat streaming session.
 *
 * Returns a unique `streamId` immediately (the renderer needs it to
 * subscribe to `wiki-chat-stream-{streamId}-chunk/done/error` channels
 * and to call `sage:unlisten` for abort). The actual HTTP POST +
 * NDJSON relay runs in the background:
 *
 *   1. POST args to /api/v1/wiki/chat/stream (camelCase→snake_case
 *      conversion is the renderer's responsibility — see
 *      api-client/wiki.ts wikiChatStream).
 *   2. Stream the NDJSON response via relayNdjsonToEvent; each event is
 *      dispatched to `sage:event:wiki-chat-stream-{streamId}-{chunk|
 *      done|error}`.
 *   3. On HTTP failure → forward `HTTP {status}` as a -error event.
 *   4. On AbortError (renderer unsubscribed via sage:unlisten) → swallow
 *      silently. Any other exception → forward `String(e)` as a -error.
 *   5. The AbortController is removed from `streamControllers` in the
 *      `finally` block regardless of outcome.
 *
 * Why a separate function (not inlined in `sage:invoke`):
 *   - Keeps the IPC handler readable.
 *   - The closure captures `webContents` and `backendUrl` cleanly, so
 *     the body of the async block doesn't have to thread them through.
 */
function startWikiChatStream(
  sender: Electron.WebContents,
  args: Record<string, unknown>,
  backendUrl: string,
): { streamId: string } {
  const streamId = `wiki-chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const controller = new AbortController();
  streamControllers.set(streamId, controller);
  const wc = BrowserWindow.fromWebContents(sender);
  if (!wc) {
    streamControllers.delete(streamId);
    throw new Error('No WebContents for invoke');
  }
  // Fire-and-forget: relay runs in background. Return streamId NOW so
  // the renderer can start subscribing to the per-id event channels.
  (async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/wiki/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(backendAuthToken ? { Authorization: `Bearer ${backendAuthToken}` } : {}),
        },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, WIKI_STREAM_ERROR);
        return;
      }
      await relayNdjsonToEvent(
        res.body as NodeJS.ReadableStream,
        `wiki-chat-stream-${streamId}`,
        wc.webContents,
        controller.signal,
      );
    } catch (e) {
      if (e instanceof Error && e.name !== 'AbortError') {
        wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, WIKI_STREAM_ERROR);
      }
    } finally {
      streamControllers.delete(streamId);
    }
  })();
  return { streamId };
}

/**
 * PR-3 Task 3: start a wiki-ingest NDJSON stream.
 *
 * Same fire-and-forget shape as `startWikiChatStream`, but the backend
 * `/ingest/stream` endpoint speaks a 3-event vocabulary
 * (progress / done / error) and the renderer `useWikiIngest` hook only
 * listens for a single `-progress` channel. The transform argument to
 * `relayNdjsonToEvent` collapses `done` → completed progress and
 * `error` → failed progress, so the hook needs no changes.
 *
 * Event-channel mapping (sent to renderer):
 *   progress → {prefix}-progress (data: raw)
 *   done     → {prefix}-progress (data: {stage:'completed', percent:100, message: JSON.stringify(raw.data)})
 *   error    → {prefix}-progress (data: {stage:'failed',    percent:0,  message: String(raw.data)})
 *   HTTP non-2xx / throw → {prefix}-progress (data: {stage:'failed', percent:0, message: 'HTTP N' | String(e)})
 */
function startWikiIngestStream(
  sender: Electron.WebContents,
  args: Record<string, unknown>,
  backendUrl: string,
): { streamId: string } {
  const streamId = `wiki-ingest-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const controller = new AbortController();
  streamControllers.set(streamId, controller);
  const wc = BrowserWindow.fromWebContents(sender);
  if (!wc) {
    streamControllers.delete(streamId);
    throw new Error('No WebContents for invoke');
  }
  // Fire-and-forget: relay runs in background. Return streamId NOW so
  // the renderer can start subscribing to the per-id event channels.
  (async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/wiki/ingest/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(backendAuthToken ? { Authorization: `Bearer ${backendAuthToken}` } : {}),
        },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(`sage:event:wiki-ingest-${streamId}-progress`, {
          stage: 'failed',
          percent: 0,
          message: WIKI_STREAM_ERROR.message,
          code: WIKI_STREAM_ERROR.code,
        });
        return;
      }
      await relayNdjsonToEvent(
        res.body as NodeJS.ReadableStream,
        `wiki-ingest-${streamId}`,
        wc.webContents,
        controller.signal,
        (rawEvent: unknown) => {
          if (typeof rawEvent !== 'object' || rawEvent === null) return null;
          const ev = (rawEvent as { event?: unknown }).event;
          if (ev === 'done') {
            // Backend done → frontend completed-progress (useWikiIngest
            // sets done=true on stage==='completed').
            return {
              suffix: '-progress',
              data: {
                stage: 'completed',
                percent: 100,
                message: JSON.stringify((rawEvent as { data?: unknown }).data),
              },
            };
          }
          if (ev === 'error') {
            return {
              suffix: '-progress',
              data: {
                stage: 'failed',
                percent: 0,
                message: WIKI_STREAM_ERROR.message,
                code: WIKI_STREAM_ERROR.code,
              },
            };
          }
          if (ev === 'progress') {
            return {
              suffix: '-progress',
              data: (rawEvent as { data?: unknown }).data,
            };
          }
          return null; // unknown event — let relay drop it
        },
      );
    } catch (e) {
      if (e instanceof Error && e.name !== 'AbortError') {
        wc.webContents.send(`sage:event:wiki-ingest-${streamId}-progress`, {
          stage: 'failed',
          percent: 0,
          message: WIKI_STREAM_ERROR.message,
          code: WIKI_STREAM_ERROR.code,
        });
      }
    } finally {
      streamControllers.delete(streamId);
    }
  })();
  return { streamId };
}

/**
 * Tear down the current backend subprocess and AWAIT its actual exit plus
 * release of the listening port before returning.
 *
 * Why async (Task 0 review round 1, finding #4):
 *   The previous sync version only fired SIGTERM and returned immediately.
 *   The auto-restart path then spawned a new backend 1-4s later, but the old
 *   child was still tearing down — under load (or on Windows where SIGTERM
 *   is unreliable) the new process would either fail to bind the port
 *   (EADDRINUSE → white screen) or get a half-released socket. We now:
 *     1. Send SIGTERM
 *     2. Wait up to BACKEND_SHUTDOWN_TIMEOUT_MS for `exit` event
 *     3. Escalate to SIGKILL if still alive
 *     4. Wait again briefly for the port to be released
 *     5. Resolve so the caller can safely respawn
 *
 * Safe to call when no backend is running (no-op).
 */
async function shutdownBackend(): Promise<void> {
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }
  const proc = backendProc;
  if (!proc) return;
  if (proc.exitCode !== null || proc.signalCode !== null) {
    backendProc = null;
    return;
  }
  backendLifecycle = 'stopping';
  logger.info('main: killing backend subprocess', { pid: proc.pid });
  const exited = new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    proc.once('exit', finish);
    // Send SIGTERM; on Win32 this maps to TerminateProcess.
    try {
      proc.kill('SIGTERM');
    } catch {
      // Already gone — `exit` will fire (or has fired) soon.
    }
    // Escalate to SIGKILL after the grace window if the child ignored
    // SIGTERM (Windows services / conda/python occasionally do).
    setTimeout(() => {
      if (proc.exitCode !== null || proc.signalCode !== null) return;
      logger.warn('main: backend did not exit on SIGTERM, escalating to SIGKILL', {
        pid: proc.pid,
      });
      try {
        proc.kill('SIGKILL');
      } catch {
        /* process already gone */
      }
      // Give SIGKILL a brief window; if it never resolves, finish() is
      // still safe to call from the caller's timeout below.
      setTimeout(finish, 500).unref();
    }, BACKEND_SHUTDOWN_TIMEOUT_MS).unref();
  });
  await exited;
  // Wait briefly for the OS to release the listening port so the next
  // spawn doesn't hit EADDRINUSE. 500ms is empirical — typical Linux /
  // Windows TIME_WAIT cleanup is <100ms.
  if (proc.pid !== undefined && proc.pid > 0) {
    await isPortReleased(BACKEND_PORT, 500);
  }
  backendProc = null;
}

/**
 * Poll until `port` on loopback has no LISTENING owner (or timeout).
 * Used by shutdownBackend to avoid respawning into EADDRINUSE.
 */
async function isPortReleased(port: number, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let occupied = false;
    try {
      const { execFileSync } = await import('node:child_process');
      if (process.platform === 'win32') {
        const out = execFileSync('netstat', ['-ano', '-p', 'TCP'], {
          encoding: 'utf8',
          timeout: 250,
        });
        const portSuffix = `:${port}`;
        for (const raw of out.split(/\r?\n/)) {
          const line = raw.trim();
          if (!line.startsWith('TCP')) continue;
          const cols = line.split(/\s+/);
          if (cols.length < 5) continue;
          if ((cols[3] ?? '') !== 'LISTENING') continue;
          if ((cols[1] ?? '').endsWith(portSuffix)) {
            occupied = true;
            break;
          }
        }
      } else {
        // `-sTCP:LISTEN` keeps noise low.
        execFileSync('lsof', ['-iTCP:' + String(port), '-sTCP:LISTEN'], {
          encoding: 'utf8',
          timeout: 250,
        });
        occupied = true;
      }
    } catch {
      // lsof exits 1 when no listeners → treat as released.
      occupied = false;
    }
    if (!occupied) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

app.whenReady().then(async () => {
  // Step 3: prune log files older than 7 days on every cold start
  cleanupOlderThan(7);
  // Phase 4: pre-launch self-check (skippable via SAGE_DOCTOR_ON_START=false for CI).
  // fail-open by design: doctor never blocks the app from launching — its output
  // is captured into the NDJSON startup log so the user can diagnose degraded
  // experiences via Show Logs. Hard 5s timeout is enforced inside runDoctorCheck.
  if (process.env.SAGE_DOCTOR_ON_START !== 'false') {
    try {
      const doctorPlan = resolveBackendLaunchCommand({
        env: process.env,
        resourcesPath: process.resourcesPath,
        platform: process.platform,
        isPackaged: app.isPackaged,
        sageDbPath: process.env.SAGE_DB_PATH ?? join(process.cwd(), 'data', 'sage.db'),
        sageUserDataDir: process.env.SAGE_USER_DATA_DIR ?? join(process.cwd(), 'data'),
        port: BACKEND_PORT,
      });
      // Round 2 (fast-follow E): thread the supervisor's launcher context
      // (command / cwd / env) into the doctor subprocess so the
      // ``import backend.main`` probe runs under the EXACT env the
      // backend will see. ``runDoctorCheck`` already merges ``options.env``
      // into the child env, so these three SAGE_BACKEND_* keys reach
      // ``backend.cli.doctor.main`` which reads them via the new
      // ``_resolve_backend_context`` helper.
      let doctorEnv: NodeJS.ProcessEnv | undefined;
      if (doctorPlan.kind === 'spawn') {
        const launcherArgv = [doctorPlan.command, ...(doctorPlan.args ?? [])];
        // Surface only the env keys the supervisor would actually set on
        // the backend (plan.env + plan.extraEnv); the host env is already
        // inherited via ``process.env`` in runDoctorCheck.
        const supervisorEnv: Record<string, string> = {};
        for (const [k, v] of Object.entries({
          ...doctorPlan.env,
          ...doctorPlan.extraEnv,
        })) {
          if (typeof v === 'string') supervisorEnv[k] = v;
        }
        doctorEnv = {
          ...supervisorEnv,
          SAGE_BACKEND_CMD: JSON.stringify(launcherArgv),
          SAGE_BACKEND_CWD: doctorPlan.cwd,
          SAGE_BACKEND_ENV: JSON.stringify(supervisorEnv),
        };
      }
      const doctorSummary =
        doctorPlan.kind === 'spawn'
          ? await runDoctorCheck({
              pythonBin: doctorPlan.command,
              packageRoot: app.isPackaged ? process.resourcesPath : process.cwd(),
              cwd: doctorPlan.cwd,
              env: doctorEnv,
              // alpha.8 (2026-08-27): 复用 BackendLaunchPlan 的 argv (含
              // dev-conda 路径 ``conda run -n sage-backend python -m ...``).
              // 不再走硬编码 ``-m backend.cli.doctor --json`` 回退, 与
              // supervisor spawnBackend 的 argv 完全对齐.
              args: doctorPlan.args,
            })
          : await runDoctorCheck(process.env.SAGE_PYTHON ?? 'python', process.cwd());
      logger.info('main: doctor check complete', doctorSummary);
      if (doctorSummary.status === 'critical') {
        logger.warn('main: doctor reported CRITICAL — user may see degraded experience', {
          summary: doctorSummary.summary,
        });
      }
    } catch (err) {
      logger.warn('main: doctor check threw', { error: String(err) });
    }
  }
  registerIpcHandlers();
  // Phase 4 lightweight smoke test path: skip backend spawn + health wait
  // (CI doesn't have the sage-backend conda env; main renderer still loads
  // and exposes window.electronAPI for IPC contract verification).
  if (process.env.SAGE_SKIP_BACKEND === '1') {
    logger.info('main: backend skipped (SAGE_SKIP_BACKEND=1)');
    // The IPC readiness gate (BackendNotReadyError) is meaningless when the
    // user (or CI) has explicitly opted out of the backend — without this,
    // smoke.spec.ts's "unknown IPC cmd" probe gets blocked at the gate before
    // reaching the dispatcher and fails the bridge round-trip assertion.
    backendLifecycle = 'ready';
    createMainWindow();
    buildApplicationMenu();
    return;
  }
  backendProc = spawnBackend();
  const ready = await waitForBackend();
  if (!ready) {
    logger.error('main: backend health timeout', {
      url: BACKEND_HEALTH,
      timeoutMs: BACKEND_HEALTH_TIMEOUT_MS,
    });
    // If spawnBackend() already surfaced a broken-installer dialog, the
    // user has the accurate cause (missing bundled Python, unsupported
    // platform, etc.). Showing a second misleading "port occupied / conda
    // not installed" dialog ~30s later would bury the real cause — skip it.
    if (reportedBrokenInstaller) {
      logger.info('main: skipping misleading 30s dialog (broken-installer already reported)');
      return;
    }
    // Step 4: replace bare app.quit() with 3-button startup-failure dialog.
    // User can open logs, retry the health check, or quit.
    const choice = await showStartupFailureDialog({
      reason: '后端服务在 30 秒内未响应',
      detail: `请检查端口 ${BACKEND_PORT} 是否被占用,或 conda 环境 sage-backend 是否已安装。`,
    });
    if (choice === 'retry') {
      const ready2 = await waitForBackend();
      if (!ready2) {
        await showStartupFailureDialog({
          reason: '后端服务在重试后仍未响应',
          detail: '已重试一次,仍无法连接',
        });
        return;
      }
      logger.info('main: backend ready', { url: BACKEND_URL });
      createMainWindow();
      buildApplicationMenu();
      return;
    }
    // 'open-logs' or 'quit' — quit is handled inside showStartupFailureDialog
    return;
  }
  logger.info('main: backend ready', { url: BACKEND_URL });
  createMainWindow();
  // Step 6: build native application menu (File / Help with log dir shortcuts)
  buildApplicationMenu();
});

app.on('window-all-closed', () => {
  // On all platforms (incl. macOS), quit when last window closes.
  // AWAIT the shutdown so the OS releases the listening port before app.quit
  // tears down the renderer. Without this, a subsequent launch on the same
  // machine can hit EADDRINUSE for up to ~3s (TIME_WAIT).
  void shutdownBackend().finally(() => {
    app.quit();
  });
});

app.on('before-quit', () => {
  appIsQuitting = true;
  void shutdownBackend();
});

app.on('activate', () => {
  // macOS: re-create window when dock icon clicked
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
