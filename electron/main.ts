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
import { join } from 'node:path';
import http from 'node:http';
import fetch from 'node-fetch';
import { invokeBackend } from './invoke';
import { relayChatStream, relayNdjsonToEvent } from './relay';
import { streamControllers } from './commands';
import { registerSkillsIpc } from './skillsIpc';
import { buildApplicationMenu } from './menu';
import { showStartupFailureDialog } from './showStartupFailureDialog';
import { cleanupOlderThan } from './logRotate';
import { registerLogIpc } from './ipc/logIpc';
import { resolveBackendLaunchCommand } from './backendLauncher';

const BACKEND_PORT = Number(process.env.PYTHON_BACKEND_PORT ?? 8765);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_HEALTH = `${BACKEND_URL}/health`;
const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged;
const VITE_DEV_URL = process.env.VITE_DEV_SERVER_URL ?? 'http://localhost:1420';

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
let mainWindow: BrowserWindow | null = null;

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
 *   1. Computes SAGE_DB_PATH (uses electron's userData when packaged).
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
  const proc = spawn(plan.cmd, plan.args, {
    env: { ...process.env, ...plan.extraEnv },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  logger.info('main: backend spawned', {
    reason: plan.reason,
    cmd: plan.cmd,
    args: plan.args,
  });

  proc.stdout?.on('data', (b) => logger.debug('backend: stdout', { line: b.toString().trim() }));
  proc.stderr?.on('data', (b) => logger.error('backend: stderr', { line: b.toString().trim() }));
  proc.on('exit', (code) => {
    logger.info('main: backend exited', { code });
    backendProc = null;
  });
  // Without an 'error' listener, Node treats spawn-time failures (binary
  // exists but is not executable, ACL block, AV lock, ENOEXEC) as uncaught
  // exceptions and crashes the Electron main process — exactly the failure
  // mode PR #130 was meant to fix. PR #130 review flagged this as issue #10.
  proc.on('error', (err) => {
    logger.error('main: backend spawn error', {
      reason: plan.reason,
      cmd: plan.cmd,
      err: String(err),
    });
    backendProc = null;
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
  stub.stdout?.on('data', (b) =>
    logger.debug('main: stub proc stdout', { reason, line: b.toString().trim() }),
  );
  stub.stderr?.on('data', (b) =>
    logger.error('main: stub proc stderr', { reason, line: b.toString().trim() }),
  );
  stub.on('exit', (code) => {
    logger.info('main: stub proc exited', { reason, code });
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
 * Poll /health until backend responds 200, with timeout.
 * Backend startup usually <2s; cap at 30s to surface real failures fast.
 */
async function waitForBackend(timeoutMs = BACKEND_HEALTH_TIMEOUT_MS): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const ok = await new Promise<boolean>((resolve) => {
        const req = http.get(BACKEND_HEALTH, (res) => {
          resolve(res.statusCode === 200);
          res.resume();
        });
        req.on('error', () => resolve(false));
        req.setTimeout(HTTP_REQUEST_TIMEOUT_MS, () => {
          req.destroy();
          resolve(false);
        });
      });
      if (ok) return true;
    } catch {
      /* ignore */
    }
    await new Promise((r) => setTimeout(r, 500));
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

  mainWindow = new BrowserWindow({
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

  // Open external links in OS browser, not in-app
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url).catch(() => undefined);
    return { action: 'deny' };
  });

  if (isDev) {
    mainWindow.loadURL(VITE_DEV_URL).catch(async (e) => {
      logger.error('main: loadURL failed', { url: VITE_DEV_URL, err: e.message });
      await showStartupFailureDialog({
        reason: '加载前端开发服务失败',
        detail: `URL: ${VITE_DEV_URL}\n错误: ${e.message}`,
      });
    });
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    // tsconfig.electron.json uses rootDirs: [electron, src], so the compiled
    // main.js lives at dist-electron/electron/main.js (one extra directory level
    // vs the legacy rootDir: electron setup). Go up two levels to reach dist/.
    const indexHtml = join(__dirname, '..', '..', 'dist', 'index.html');
    logger.info('main: loading frontend', { path: indexHtml, __dirname });
    mainWindow.loadFile(indexHtml).catch(async (e) => {
      logger.error('main: loadFile failed', { path: indexHtml, err: e.message });
      await showStartupFailureDialog({
        reason: '加载前端资源失败',
        detail: `路径: ${indexHtml}\n错误: ${e.message}`,
      });
    });
    // Diagnostic: log when page finishes loading (or fails)
    mainWindow.webContents.on('did-finish-load', () => {
      if (mainWindow) {
        logger.info('main: frontend did-finish-load', { url: mainWindow.webContents.getURL() });
      }
    });
    mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription) => {
      logger.error('main: frontend did-fail-load', { errorCode, errorDescription });
    });
    // Diagnostic: capture console messages (JS errors, warnings, logs)
    mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
      const logLevel = level === 0 ? 'debug' : level === 1 ? 'info' : level === 2 ? 'warn' : 'error';
      logger[logLevel]('main: frontend console', { level, message, line, sourceId });
    });
    // Diagnostic: capture page crashes (using non-deprecated render-process-gone)
    mainWindow.webContents.on('render-process-gone', (_event, details) => {
      logger.error('main: frontend render-process-gone', {
        reason: details.reason,
        exitCode: details.exitCode,
      });
    });
    mainWindow.webContents.on('unresponsive', () => {
      logger.error('main: frontend unresponsive');
    });
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
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
      if (payload.cmd === 'wiki_chat_stream') {
        return startWikiChatStream(_evt.sender, payload.args ?? {}, BACKEND_URL);
      }
      if (payload.cmd === 'wiki_ingest_stream') {
        return startWikiIngestStream(_evt.sender, payload.args ?? {}, BACKEND_URL);
      }
      try {
        return await invokeBackend(payload.cmd, payload.args ?? {}, BACKEND_URL);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        logger.error('ipc: invoke failed', { cmd: payload.cmd, err: msg });
        throw new Error(msg);
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
        relayChatStream(senderWebContents, event, streamId, BACKEND_URL, abort.signal).catch(
          (e) => {
            if (e instanceof Error && e.name !== 'AbortError') {
              logger.error('ipc: relay error', { event, err: e.message });
            }
          },
        );
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
  registerSkillsIpc((channel, handler) => {
    ipcMain.handle(channel, handler as Parameters<typeof ipcMain.handle>[1]);
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, {
          error: `HTTP ${res.status}`,
        });
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
        wc.webContents.send(`sage:event:wiki-chat-stream-${streamId}-error`, { error: String(e) });
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        wc.webContents.send(`sage:event:wiki-ingest-${streamId}-progress`, {
          stage: 'failed',
          percent: 0,
          message: `HTTP ${res.status}`,
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
                message: String((rawEvent as { data?: unknown }).data ?? 'unknown error'),
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
          message: String(e),
        });
      }
    } finally {
      streamControllers.delete(streamId);
    }
  })();
  return { streamId };
}

function shutdownBackend(): void {
  if (backendProc && backendProc.exitCode === null) {
    logger.info('main: killing backend subprocess');
    backendProc.kill('SIGTERM');
    // Give it 3s to exit cleanly, then SIGKILL
    setTimeout(() => {
      if (backendProc && backendProc.exitCode === null) {
        backendProc.kill('SIGKILL');
      }
    }, BACKEND_SHUTDOWN_TIMEOUT_MS);
  }
}

app.whenReady().then(async () => {
  // Step 3: prune log files older than 7 days on every cold start
  cleanupOlderThan(7);
  registerIpcHandlers();
  // Phase 4 lightweight smoke test path: skip backend spawn + health wait
  // (CI doesn't have the sage-backend conda env; main renderer still loads
  // and exposes window.electronAPI for IPC contract verification).
  if (process.env.SAGE_SKIP_BACKEND === '1') {
    logger.info('main: backend skipped (SAGE_SKIP_BACKEND=1)');
    createMainWindow();
    buildApplicationMenu();
    return;
  }
  backendProc = spawnBackend();
  // If the resolver already fired the broken-installer dialog (because
  // bundled Python is missing or the platform is unsupported), suppress the
  // generic health-timeout dialog below so the user doesn't see two stacked
  // modal dialogs describing the same problem from different angles.
  if (reportedBrokenInstaller) {
    logger.info('main: skipping health-timeout dialog (broken-installer dialog already shown)');
    return;
  }
  const ready = await waitForBackend();
  if (!ready) {
    logger.error('main: backend health timeout', {
      url: BACKEND_HEALTH,
      timeoutMs: BACKEND_HEALTH_TIMEOUT_MS,
    });
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
  // On all platforms (incl. macOS), quit when last window closes
  shutdownBackend();
  app.quit();
});

app.on('before-quit', shutdownBackend);

app.on('activate', () => {
  // macOS: re-create window when dock icon clicked
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
