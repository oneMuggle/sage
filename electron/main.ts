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
    process.platform === 'win32' && existsSync(join(process.resourcesPath ?? '', 'python', 'python.exe'))
      ? join(process.resourcesPath, 'python', 'python.exe')
      : null;

  let proc: ChildProcess;
  if (pyLauncher) {
    // Packaged Win: launch bundled Python directly
    proc = spawn(pyLauncher, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
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
const COMMAND_ROUTES: Record<string, { method: string; path: (args: Record<string, unknown>) => string }> = {
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
    throw new Error(`Unknown IPC command: ${cmd} (Phase 1 stub: see COMMAND_ROUTES in electron/main.ts)`);
  }
  const url = `${BACKEND_URL}${route.path(args)}`;
  const init: RequestInit = { method: route.method, headers: { 'Content-Type': 'application/json' } };
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
  ipcMain.handle('sage:invoke', async (_evt, payload: { cmd: string; args?: Record<string, unknown> }) => {
    try {
      return await invokeBackend(payload.cmd, payload.args ?? {});
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[ipc:sage:invoke] ${payload.cmd} failed:`, msg);
      throw new Error(msg);
    }
  });

  // Phase 1 stub: listen() forwards to a no-op UnlistenFn.
  // Phase 2 will wire this to backend SSE/WS relay via webContents.send().
  ipcMain.handle('sage:listen', async (_evt, payload: { event: string }) => {
    console.log(`[ipc:sage:listen] subscribed (Phase 1 stub): ${payload.event}`);
    return { ok: true, event: payload.event, _note: 'Phase 1 stub; relay in Phase 2' };
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