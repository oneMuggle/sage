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

vi.mock('child_process', () => ({ spawn: vi.fn() }));
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

describe('backend exit auto-restart logic (PR-B)', () => {
  beforeEach(() => {
    vi.mocked(mainWindow.webContents.send).mockClear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('emits backend:disconnected with attempt=1 on first call', () => {
    scheduleBackendRestart();
    expect(mainWindow.webContents.send).toHaveBeenCalledWith(
      'backend:disconnected',
      { attempt: 1 },
    );
  });

  it('emits backend:disconnected with attempt=-1 after 3 attempts', () => {
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    expect(mainWindow.webContents.send).toHaveBeenLastCalledWith(
      'backend:disconnected',
      { attempt: -1 },
    );
  });
});