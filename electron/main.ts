/* eslint-disable */
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
import { COMMAND_ROUTES, UnknownIpcCommandError } from './commands';
import { relayChatStream } from './relay';

const BACKEND_PORT = Number(process.env.PYTHON_BACKEND_PORT ?? 8765);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_HEALTH = `${BACKEND_URL}/health`;
const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged;
const VITE_DEV_URL = process.env.VITE_DEV_SERVER_URL ?? 'http://localhost:1420';

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
//   - --js-flags=--max-old-space-size=2048: cap V8 heap to 2GB so Win7
//     systems with 4GB RAM don't OOM-kill during chat streaming.
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');
app.commandLine.appendSwitch('in-process-gpu');
app.commandLine.appendSwitch('disable-features', 'VizDisplayCompositor');
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=2048');

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

  let proc: ChildProcess;
  if (pyLauncher) {
    // Packaged Win: launch bundled Python directly
    proc = spawn(
      pyLauncher,
      ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
      {
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
  } else {
    // Dev: delegate to conda
    proc = spawn(condaCmd, condaArgs, {
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
async function waitForBackend(timeoutMs = 30_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const ok = await new Promise<boolean>((resolve) => {
        const req = http.get(BACKEND_HEALTH, (res) => {
          resolve(res.statusCode === 200);
          res.resume();
        });
        req.on('error', () => resolve(false));
        req.setTimeout(1000, () => {
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
 */

// Bridge invoke(agent_chat_stream) → listen(chat-stream-{streamId}):
// renderer first invokes to get a streamId, then subscribes via listen();
// we cache the original request args by streamId so the listen phase can
// replay them when opening the actual NDJSON stream to the renderer.
const pendingChatArgs = new Map<string, Record<string, unknown>>();

async function invokeBackend(cmd: string, args: Record<string, unknown> = {}): Promise<unknown> {
  const route = COMMAND_ROUTES[cmd];
  if (!route) {
    throw new UnknownIpcCommandError(cmd);
  }
  const url = `${BACKEND_URL}${route.path(args)}`;
  const init: RequestInit = {
    method: route.method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    init.body = JSON.stringify(args);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Backend ${route.method} ${url} → ${res.status}: ${text}`);
  }
  // chat/stream returns NDJSON: read the first line to obtain a streamId
  // metadata (backend may emit it on the first line), then close the body
  // — the relay phase (sage:listen) re-issues a fresh POST to stream events
  // to the renderer. We cache the original args by streamId so the listen
  // handler can replay the request.
  if (route.isSse) {
    if (!res.body) {
      throw new Error(`Backend ${route.method} ${url} returned no body for SSE`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const { value } = await reader.read();
    reader.cancel().catch(() => undefined);
    const firstLine = decoder.decode(value).split('\n')[0].trim();
    let streamId: string;
    try {
      const parsed = JSON.parse(firstLine) as { streamId?: unknown };
      streamId =
        typeof parsed.streamId === 'string' && parsed.streamId
          ? parsed.streamId
          : String((args.session_id as string | undefined) ?? '');
    } catch {
      streamId = String((args.session_id as string | undefined) ?? '');
    }
    pendingChatArgs.set(streamId, args);
    return streamId;
  }
  return res.json();
}

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 640,
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
        return await invokeBackend(payload.cmd, payload.args ?? {});
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
        const args = pendingChatArgs.get(streamId) ?? {};
        pendingChatArgs.delete(streamId);
        relayChatStream(senderWebContents, event, streamId, args, BACKEND_URL, abort.signal).catch(
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
        // Free cached chat args too so a re-listen for the same streamId
        // doesn't pick up stale args from a previous request.
        if (event.startsWith('chat-stream-')) {
          pendingChatArgs.delete(event.replace(/^chat-stream-/, ''));
        }
        console.log(`[ipc:sage:unlisten] aborted: ${event}`);
      }
      return { ok: true };
    },
  );
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
    }, 3000);
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
