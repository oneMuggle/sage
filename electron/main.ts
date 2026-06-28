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
import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { spawn, ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import http from 'node:http';
import fetch from 'node-fetch';
import { invokeBackend } from './invoke';
import { relayChatStream } from './relay';

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

/**
 * Locate the Python interpreter for the sage-backend conda env.
 * - Dev (running from repo): use `conda run -n sage-backend python`
 * - Packaged app: ship a launcher script (electron-builder extraResources)
 *
 * Phase 1 implementation: only handles dev path; packaged launcher is
 * Phase 3 work (Win7 NSIS installer extraResources section).
 */
function spawnBackend(): ChildProcess {
  // Pick the right launcher based on platform / packaging
  const condaCmd = process.env.SAGE_PYTHON ?? 'conda';
  // Run as a module so `from backend.adapters...` absolute imports resolve
  // (running `python backend/main.py` puts the script's dir on sys.path[0],
  // which makes the `backend` package unfindable).
  const condaArgs = ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'];

  // On Windows, prefer `pythonw` (no console) when packaged; fallback to `python`
  const pyLauncher =
    process.platform === 'win32' &&
    existsSync(join(process.resourcesPath ?? '', 'python', 'python.exe'))
      ? join(process.resourcesPath, 'python', 'python.exe')
      : null;

  // Resolve SAGE_DB_PATH once so both packaged and dev spawn paths share it.
  // Backend prefers this env var; falls back to:
  //   - Dev (running from repo): <repo>/data/sage.db (project-local DB so
  //     developers see their existing session history during `npm run electron:dev`).
  //   - Packaged app: userData/sage.db (per-user writable location).
  // SAGE_DB_PATH env var always wins (for CI / override scenarios).
  const sageDbPath =
    process.env.SAGE_DB_PATH ??
    (app.isPackaged
      ? join(app.getPath('userData'), 'sage.db')
      : join(process.cwd(), 'data', 'sage.db'));

  let proc: ChildProcess;
  if (pyLauncher) {
    // Packaged Win: launch bundled Python directly
    // Set PYTHONPATH to include backend and sage-core from resources
    const pythonPath = [
      join(process.resourcesPath, 'backend'),
      join(process.resourcesPath, 'sage-core'),
    ].join(process.platform === 'win32' ? ';' : ':');

    proc = spawn(
      pyLauncher,
      ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
      {
        env: {
          ...process.env,
          SAGE_DB_PATH: sageDbPath,
          PYTHONPATH: pythonPath,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
  } else {
    // Dev: delegate to conda
    proc = spawn(condaCmd, condaArgs, {
      env: { ...process.env, SAGE_DB_PATH: sageDbPath },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  }

  proc.stdout?.on('data', (b) => process.stdout.write(`[backend] ${b}`));
  proc.stderr?.on('data', (b) => process.stderr.write(`[backend:err] ${b}`));
  proc.on('exit', (code) => {
    console.log(`[backend] exited with code ${code}`);
    backendProc = null;
  });
  return proc;
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
  mainWindow = new BrowserWindow({
    width: DEFAULT_WINDOW_WIDTH,
    height: DEFAULT_WINDOW_HEIGHT,
    minWidth: MIN_WINDOW_WIDTH,
    minHeight: MIN_WINDOW_HEIGHT,
    title: 'Sage',
    icon: join(__dirname, '..', 'build', 'icon.ico'),
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
    mainWindow.loadURL(VITE_DEV_URL).catch((e) => console.error('Failed to load Vite dev URL:', e));
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    const indexHtml = join(__dirname, '..', 'dist', 'index.html');
    mainWindow.loadFile(indexHtml).catch((e) => console.error('Failed to load index.html:', e));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function registerIpcHandlers(): void {
  ipcMain.handle(
    'sage:invoke',
    async (_evt, payload: { cmd: string; args?: Record<string, unknown> }) => {
      try {
        return await invokeBackend(payload.cmd, payload.args ?? {}, BACKEND_URL);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.error(`[ipc:sage:invoke] ${payload.cmd} failed:`, msg);
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
      console.log(`[ipc:sage:listen] subscribe: ${event}`);

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
              console.error(`[relay ${event}] error:`, e.message);
            }
          },
        );
        return { ok: true, event };
      }

      // Unknown event: log + no-op (frontend listen() Promise still resolves)
      console.warn(`[ipc:sage:listen] unknown event pattern (no relay): ${event}`);
      return { ok: true, event };
    },
  );

  ipcMain.handle(
    'sage:unlisten',
    async (_evt, payload: { event: string }): Promise<{ ok: true }> => {
      const { event } = payload;
      const abort = eventSubscriptions.get(event);
      if (abort) {
        abort.abort();
        eventSubscriptions.delete(event);
        console.log(`[ipc:sage:unlisten] aborted: ${event}`);
      }
      return { ok: true };
    },
  );

  // === Theme IPC handlers (M2 P2) ===
  // Bridge the 7 P1 backend REST endpoints to the renderer through ipcRenderer.invoke.
  // Each handler forwards the call to FastAPI on BACKEND_URL and returns the
  // parsed JSON envelope. On network / HTTP errors we return the same envelope
  // shape the backend uses ({success:false, error, code}) so the renderer's
  // themeCssClient sees a uniform contract regardless of failure source.
  const themeUrl = (path: string): string => `${BACKEND_URL}${path}`;

  const themeBridgeFailed = (e: unknown): {
    success: false;
    error: string;
    code: string;
  } => ({
    success: false,
    error: e instanceof Error ? e.message : String(e),
    code: 'IPC_BRIDGE_FAILED',
  });

  ipcMain.handle('theme:list', async () => {
    try {
      const resp = await fetch(themeUrl('/api/v1/theme/list'));
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error('[ipc:theme:list] failed:', e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:get', async (_evt, id: string) => {
    try {
      const resp = await fetch(themeUrl(`/api/v1/theme/get/${encodeURIComponent(id)}`));
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error(`[ipc:theme:get] ${id} failed:`, e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:save', async (_evt, preset: unknown) => {
    try {
      const resp = await fetch(themeUrl('/api/v1/theme/save'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(preset),
      });
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error('[ipc:theme:save] failed:', e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:delete', async (_evt, id: string) => {
    try {
      const resp = await fetch(
        themeUrl(`/api/v1/theme/delete/${encodeURIComponent(id)}`),
        { method: 'DELETE' },
      );
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error(`[ipc:theme:delete] ${id} failed:`, e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:getActive', async () => {
    try {
      const resp = await fetch(themeUrl('/api/v1/theme/active'));
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error('[ipc:theme:getActive] failed:', e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:saveActive', async (_evt, active: unknown) => {
    try {
      const resp = await fetch(themeUrl('/api/v1/theme/active'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(active),
      });
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error('[ipc:theme:saveActive] failed:', e);
      return themeBridgeFailed(e);
    }
  });

  ipcMain.handle('theme:validate', async (_evt, css: string) => {
    try {
      const resp = await fetch(themeUrl('/api/v1/theme/validate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ css }),
      });
      return (await resp.json()) as unknown;
    } catch (e) {
      console.error('[ipc:theme:validate] failed:', e);
      return themeBridgeFailed(e);
    }
  });
}

function shutdownBackend(): void {
  if (backendProc && backendProc.exitCode === null) {
    console.log('[main] killing backend subprocess');
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
  registerIpcHandlers();
  // Phase 4 lightweight smoke test path: skip backend spawn + health wait
  // (CI doesn't have the sage-backend conda env; main renderer still loads
  // and exposes window.electronAPI for IPC contract verification).
  if (process.env.SAGE_SKIP_BACKEND === '1') {
    console.log('[main] SAGE_SKIP_BACKEND=1 — skipping backend spawn');
    createMainWindow();
    return;
  }
  backendProc = spawnBackend();
  const ready = await waitForBackend();
  if (!ready) {
    console.error('[main] backend failed to become healthy within 30s');
    app.quit();
    return;
  }
  console.log(`[main] backend ready at ${BACKEND_URL}`);
  createMainWindow();
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
