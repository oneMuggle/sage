// electron/test_backend_auto_restart.test.ts
// PR-B: backend auto-restart logic.
//
// This test is intentionally RED at the time of writing — it assumes
// - `scheduleBackendRestart` is exported from `./main` (added by Task 10)
// - `electron/mainWindow.ts` exists and exports a `mainWindow` singleton
//   with `webContents.send` (added by Task 10).
//
// Per TDD, the RED-on-import failure is the *correct* state at this stage.
// Task 10 will turn these tests GREEN by introducing the exports.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('child_process', () => {
  const noop = () => {};
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
  BrowserWindow: vi.fn(),
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
vi.mock('./mainWindow', () => ({
  mainWindow: {
    webContents: { send: vi.fn() },
  },
}));

import { scheduleBackendRestart } from './main';
import { mainWindow } from './mainWindow';

// Test mock injects a non-null BrowserWindow; the production type allows null.
// `!` here is the standard vitest pattern for "test fixture is guaranteed".
const win = mainWindow!;

describe('backend exit auto-restart logic (PR-B)', () => {
  beforeEach(() => {
    vi.mocked(win.webContents.send).mockClear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('emits backend:disconnected with attempt=1 on first call', () => {
    scheduleBackendRestart();
    expect(win.webContents.send).toHaveBeenCalledWith('backend:disconnected', { attempt: 1 });
  });

  it('emits backend:disconnected with attempt=-1 after 3 attempts', () => {
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    expect(win.webContents.send).toHaveBeenLastCalledWith(
      'backend:disconnected',
      { attempt: -1 },
    );
  });
});