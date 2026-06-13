/**
 * Electron main process — Sage desktop shell
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

const BACKEND_PORT = Number(process.env.PYTHON_BACKEND_PORT ?? 8765);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_HEALTH = `${BACKEND_URL}/health`;
const isDev = !app.isPackaged;
const VITE_DEV_URL = process.env.VITE_DEV_SERVER_URL ?? 'http://localhost:1420';

// Win7 compat: disable GPU + sandbox BEFORE app ready
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');

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
  const condaArgs = ['run', '-n', 'sage-backend', 'python', 'backend/main.py'];

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
const COMMAND_ROUTES: Record<
  string,
  { method: string; path: (args: Record<string, unknown>) => string }
> = {
  // chat
  agent_chat_stream: { method: 'POST', path: () => '/chat/stream' },
  interrupt_agent: { method: 'POST', path: () => '/interrupt' },
  // sessions
  delete_session: { method: 'DELETE', path: (a) => `/sessions/${a.id}` },
  delete_message: { method: 'POST', path: (a) => `/messages/${a.id}/delete` },
  // memory
  delete_memory: { method: 'POST', path: () => '/memory/delete' },
  // evolution
  trigger_evolution: { method: 'POST', path: () => '/evolution/trigger' },
};

async function invokeBackend(cmd: string, args: Record<string, unknown> = {}): Promise<unknown> {
  const route = COMMAND_ROUTES[cmd];
  if (!route) {
    throw new Error(
      `Unknown IPC command: ${cmd} (Phase 1 stub: see COMMAND_ROUTES in electron/main.ts)`,
    );
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
  // chat/stream returns SSE; for Phase 1 minimal, just resolve with first event
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('text/event-stream')) {
    return { streamId: args.session_id ?? 'pending', _note: 'Phase 1 stub: SSE relay in Phase 2' };
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
        relayChatStream(senderWebContents, event, streamId, abort.signal).catch((e) => {
          if (e instanceof Error && e.name !== 'AbortError') {
            console.error(`[relay ${event}] error:`, e.message);
          }
        });
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
}

/**
 * Open streaming HTTP connection to backend chat stream endpoint and forward
 * each NDJSON line as a webContents.send event.
 *
 * Backend currently exposes /chat/stream (POST) that creates AND streams in
 * one call. Phase 2 best-effort: POST the chat request with the streamId,
 * read NDJSON response. If backend has no such endpoint, this fails silently
 * and the frontend's listen() Promise still resolves.
 */
async function relayChatStream(
  webContents: Electron.WebContents,
  event: string,
  streamId: string,
  signal: AbortSignal,
): Promise<void> {
  // The streamId was generated by the renderer's invoke('agent_chat_stream').
  // We re-issue a POST to /chat/stream with a marker so backend knows to
  // resume streaming the same stream. If backend doesn't support replay,
  // the fetch will return 4xx and we log + bail.
  const url = `${BACKEND_URL}/chat/stream/${encodeURIComponent(streamId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: 'GET',
      signal,
      headers: { Accept: 'application/x-ndjson, application/json' },
    });
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    console.warn(`[relay ${event}] fetch failed (${url}):`, e instanceof Error ? e.message : e);
    return;
  }

  if (!res.ok || !res.body) {
    console.warn(`[relay ${event}] backend returned ${res.status} for ${url}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const payload = JSON.parse(trimmed);
          webContents.send(`sage:event:${event}`, payload);
        } catch {
          // Non-JSON line: forward raw
          webContents.send(`sage:event:${event}`, { raw: trimmed });
        }
      }
    }
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    console.error(`[relay ${event}] stream error:`, e instanceof Error ? e.message : e);
  }
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
