// electron/test_backend_auto_restart.test.ts
// PR-B: backend auto-restart logic.
//
// Module-state isolation: scheduleBackendRestart relies on module-scoped
// state (`restartCount`, `restartTimer`, `appIsQuitting`) declared in
// electron/main.ts. Vitest's per-file module cache means a second `it()`
// in the same file would see the timer still armed from the first test
// (vi.useFakeTimers prevents it from firing → early-return forever). To
// get a clean slate per test, reset modules and re-import the function.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('child_process', () => {
  const eventEmitter = {
    on: vi.fn(),
    once: vi.fn(),
    emit: vi.fn(),
    removeListener: vi.fn(),
    stdout: { on: vi.fn(), once: vi.fn() },
    stderr: { on: vi.fn(), once: vi.fn() },
    kill: vi.fn(),
  };
  return {
    spawn: vi.fn(() => eventEmitter),
    execSync: vi.fn(),
    default: { spawn: vi.fn(() => eventEmitter), execSync: vi.fn() },
  };
});
vi.mock('node:child_process', () => {
  const eventEmitter = {
    on: vi.fn(),
    once: vi.fn(),
    emit: vi.fn(),
    removeListener: vi.fn(),
    stdout: { on: vi.fn(), once: vi.fn() },
    stderr: { on: vi.fn(), once: vi.fn() },
    kill: vi.fn(),
  };
  return {
    spawn: vi.fn(() => eventEmitter),
    execSync: vi.fn(),
    default: { spawn: vi.fn(() => eventEmitter), execSync: vi.fn() },
  };
});
vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    disableHardwareAcceleration: vi.fn(),
    commandLine: { appendSwitch: vi.fn() },
    whenReady: vi.fn(() => Promise.resolve()),
    on: vi.fn(),
    quit: vi.fn(),
    getPath: vi.fn(() => '/tmp/userdata'),
  },
  Menu: { buildFromTemplate: vi.fn(), setApplicationMenu: vi.fn() },
  clipboard: { writeText: vi.fn() },
  BrowserWindow: vi.fn(() => ({
    webContents: {
      setWindowOpenHandler: vi.fn(),
      on: vi.fn(),
      getURL: vi.fn(() => 'http://localhost:1420/'),
    },
    on: vi.fn(),
    loadURL: vi.fn(() => Promise.resolve()),
    loadFile: vi.fn(() => Promise.resolve()),
  })),
  dialog: { showOpenDialog: vi.fn() },
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  shell: { openExternal: vi.fn() },
}));
vi.mock('./backendLauncher', () => ({
  resolveBackendLaunchCommand: vi.fn().mockReturnValue({
    kind: 'spawn',
    cmd: 'fake-python',
    args: [],
    extraEnv: {},
    reason: 'test',
  }),
}));

describe('backend exit auto-restart logic (PR-B)', () => {
  // Per-test fresh module: vi.resetModules() drops the cached
  // electron/main.ts module so a re-import gives a new
  // restartCount=0, restartTimer=null, appIsQuitting=false slate.
  let mainWindow: { webContents: { send: ReturnType<typeof vi.fn> } };
  let scheduleBackendRestart: () => void;

  beforeEach(async () => {
    vi.resetModules();
    const mockMainWindow = { webContents: { send: vi.fn() } };
    // mainWindow is re-created with the freshly-reset module each test.
    vi.doMock('./mainWindow', () => ({ mainWindow: mockMainWindow, setMainWindow: vi.fn() }));
    const mainMod = await import('./main');
    scheduleBackendRestart = mainMod.scheduleBackendRestart;
    mainWindow = mockMainWindow;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('emits backend:disconnected with attempt=1 on first call', () => {
    scheduleBackendRestart();

    expect(mainWindow.webContents.send).toHaveBeenCalledWith('backend:disconnected', {
      attempt: 1,
    });
    expect(vi.getTimerCount()).toBe(1);
  });

  it('does not schedule duplicate retries for repeated exit events', () => {
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();

    const disconnectedCalls = mainWindow.webContents.send.mock.calls.filter(
      ([channel]) => channel === 'backend:disconnected',
    );
    expect(disconnectedCalls).toEqual([['backend:disconnected', { attempt: 1 }]]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('emits attempt=-1 after three elapsed retry attempts', async () => {
    scheduleBackendRestart();
    vi.advanceTimersByTime(1000);
    await Promise.resolve();

    scheduleBackendRestart();
    vi.advanceTimersByTime(2000);
    await Promise.resolve();

    scheduleBackendRestart();
    vi.advanceTimersByTime(4000);
    await Promise.resolve();

    scheduleBackendRestart();

    const disconnectedCalls = mainWindow.webContents.send.mock.calls.filter(
      ([channel]) => channel === 'backend:disconnected',
    );
    expect(disconnectedCalls).toEqual([
      ['backend:disconnected', { attempt: 1 }],
      ['backend:disconnected', { attempt: 2 }],
      ['backend:disconnected', { attempt: 3 }],
      ['backend:disconnected', { attempt: -1 }],
    ]);
    // Exhausted state: no further timer armed. Locks the contract that
    // `restartCount >= MAX_RESTART_ATTEMPTS` early-returns before
    // `setTimeout` so a future refactor can't silently keep retrying.
    expect(vi.getTimerCount()).toBe(0);
  });
});
