/**
 * Regression: `pet:states` must only be broadcast when a per-pet snapshot
 * actually changed. Stream events call emit() far more often than the 500ms
 * tick, and an unconditional broadcast makes every InAppPet dock re-render
 * per token.
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => {
  class FakeBrowserWindow {
    webContents = { setWindowOpenHandler: vi.fn(), on: vi.fn(), send: vi.fn() };
    on = vi.fn();
    once = vi.fn();
    loadURL = vi.fn(() => Promise.resolve());
    loadFile = vi.fn(() => Promise.resolve());
    isDestroyed = vi.fn(() => false);
  }
  return {
    BrowserWindow: FakeBrowserWindow,
    Menu: { buildFromTemplate: vi.fn() },
    screen: {
      getCursorScreenPoint: vi.fn(() => ({ x: 0, y: 0 })),
      getDisplayNearestPoint: vi.fn(() => ({
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
    },
  };
});

vi.mock('../logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import { PetController } from '../pet/controller';

describe('PetController in-app state broadcast', () => {
  let dir: string | null = null;

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = null;
  });

  it('does not rebroadcast pet:states when nothing changed', () => {
    dir = mkdtempSync(join(tmpdir(), 'sage-pet-controller-'));
    const send = vi.fn();
    const main = {
      isDestroyed: () => false,
      webContents: { id: 1, send },
    };
    const controller = new PetController({
      backendUrl: 'http://127.0.0.1:1',
      getAuthToken: () => null,
      getMainWindow: () => main as unknown as Electron.BrowserWindow,
      devUrl: 'http://localhost:1420',
      isPackaged: true,
      userDataDir: dir,
    });

    // In-app only: no overlay windows get created for this test.
    controller.setConfig({ enabled: true, displayMode: 'in-app' });
    send.mockClear();

    const emit = (controller as unknown as { emit: (force?: boolean) => void }).emit.bind(
      controller,
    );
    emit();
    emit();

    const stateSends = send.mock.calls.filter(([channel]) => channel === 'pet:states');
    expect(stateSends).toHaveLength(0);
  });
});
