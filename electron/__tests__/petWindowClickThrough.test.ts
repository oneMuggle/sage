/**
 * Regression: click-through must never be restored on a window that does not
 * use the pointer-polling mechanism (opaque compatibility window, or polling
 * fallback). Otherwise `endDrag()`/`hide()` would leave the pet permanently
 * click-through with no code path to make it interactive again.
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import type { PetRenderConfig } from '../pet/types';
import { PetWindow } from '../pet/windows';

interface FakeWindow {
  options: unknown;
  setIgnoreMouseEvents: ReturnType<typeof vi.fn>;
  setBounds: ReturnType<typeof vi.fn>;
  setSize: ReturnType<typeof vi.fn>;
  setPosition: ReturnType<typeof vi.fn>;
  showInactive: ReturnType<typeof vi.fn>;
  loadURL: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  hide: ReturnType<typeof vi.fn>;
}

const { fakeWindows } = vi.hoisted(() => ({ fakeWindows: [] as unknown[] }));

vi.mock('electron', () => {
  class FakeBrowserWindow {
    options: unknown;
    webContents = { setWindowOpenHandler: vi.fn(), on: vi.fn(), send: vi.fn() };
    setAlwaysOnTop = vi.fn();
    on = vi.fn();
    once = vi.fn();
    loadURL = vi.fn(() => Promise.resolve());
    loadFile = vi.fn(() => Promise.resolve());
    setIgnoreMouseEvents = vi.fn();
    bounds = { x: 1023, y: 715, width: 520, height: 365 };
    getBounds = vi.fn(() => ({ ...this.bounds }));
    setBounds = vi.fn((next: { x: number; y: number; width: number; height: number }) => {
      this.bounds = { ...next };
    });
    setSize = vi.fn();
    setPosition = vi.fn();
    showInactive = vi.fn();
    isVisible = vi.fn(() => true);
    hide = vi.fn();
    destroy = vi.fn();
    isDestroyed = vi.fn(() => false);

    constructor(options: unknown) {
      this.options = options;
      fakeWindows.push(this);
    }
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

function makeConfig(overrides: Partial<PetRenderConfig> = {}): PetRenderConfig {
  return {
    version: 2,
    enabled: true,
    displayMode: 'desktop',
    tempo: 'standard',
    reduceMotion: false,
    bubbleMode: 'important',
    soundScenes: { waiting: true, error: false, done: false },
    showSessionTitle: false,
    compatibilityMode: 'auto',
    followActiveSession: true,
    externalApi: false,
    pets: [{ id: 'default', petPack: 'dafeiyu', size: 'medium' }],
    petId: 'default',
    petPack: 'dafeiyu',
    size: 'medium',
    ...overrides,
  };
}

const cleanup: Array<{ window: PetWindow; dir: string }> = [];

function createPetWindow(
  compatibilityMode: PetRenderConfig['compatibilityMode'],
  overrides: Partial<PetRenderConfig> = {},
): {
  petWindow: PetWindow;
  win: FakeWindow;
  dir: string;
} {
  const dir = mkdtempSync(join(tmpdir(), 'sage-pet-window-test-'));
  const petWindow = new PetWindow({
    config: makeConfig({ compatibilityMode, ...overrides }),
    petId: 'default',
    instanceIndex: 0,
    devUrl: 'http://localhost:1420',
    isPackaged: false,
    userDataDir: dir,
  });
  petWindow.create();
  cleanup.push({ window: petWindow, dir });
  return {
    petWindow,
    win: fakeWindows[fakeWindows.length - 1] as FakeWindow,
    dir,
  };
}

afterEach(() => {
  for (const entry of cleanup.splice(0)) {
    entry.window.destroy();
    rmSync(entry.dir, { recursive: true, force: true });
  }
  fakeWindows.length = 0;
});

describe('PetWindow click-through', () => {
  it('keeps the opaque compatibility window interactive after a drag', () => {
    const { petWindow, win } = createPetWindow('on');

    petWindow.startDrag();
    petWindow.endDrag();

    expect(win.setIgnoreMouseEvents).not.toHaveBeenCalledWith(true, expect.anything());
    expect(win.setIgnoreMouseEvents).not.toHaveBeenCalledWith(true);
  });

  it('keeps the opaque compatibility window interactive after hide()', () => {
    const { petWindow, win } = createPetWindow('on');

    petWindow.startDrag();
    petWindow.endDrag();
    petWindow.hide();

    expect(win.setIgnoreMouseEvents).not.toHaveBeenCalledWith(true, expect.anything());
    expect(win.setIgnoreMouseEvents).not.toHaveBeenCalledWith(true);
  });

  it('still restores click-through for the transparent overlay after a drag', () => {
    const { petWindow, win } = createPetWindow('off');

    // Initial state: click-through with forward.
    expect(win.setIgnoreMouseEvents).toHaveBeenCalledWith(true, { forward: true });
    win.setIgnoreMouseEvents.mockClear();

    petWindow.startDrag();
    petWindow.endDrag();

    expect(win.setIgnoreMouseEvents.mock.calls).toEqual([[false], [true, { forward: true }]]);
  });
});

describe('PetWindow status panel (separate window)', () => {
  it('opens the panel in its own window without moving or resizing the overlay', () => {
    const { petWindow, win } = createPetWindow('on', { size: 'huge' });
    expect(fakeWindows).toHaveLength(1);

    petWindow.setPanelOpen(true);

    expect(fakeWindows).toHaveLength(2);
    const panel = fakeWindows[1] as unknown as FakeWindow;
    expect(panel.loadURL).toHaveBeenCalledWith('http://localhost:1420/pet.html?panel=1');
    // Centered above the pet, clamped to the work area.
    expect(panel.setBounds).toHaveBeenCalledWith(
      { x: 1043, y: 347, width: 480, height: 360 },
      false,
    );
    expect(panel.showInactive).toHaveBeenCalled();
    // focusable:false keeps the panel out of the WM's management on X11, so
    // it stays above normal windows exactly like the overlay.
    const panelOptions = (panel as unknown as { options: { focusable?: boolean } }).options;
    expect(panelOptions.focusable).toBe(false);
    // The overlay must stay put — moving/resizing it made the sprite jump.
    expect(win.setBounds).not.toHaveBeenCalled();
    expect(win.setSize).not.toHaveBeenCalled();
    expect(win.setPosition).not.toHaveBeenCalled();
  });

  it('hides the panel on close and when the pet is hidden', () => {
    const { petWindow } = createPetWindow('on', { size: 'huge' });

    petWindow.setPanelOpen(true);
    expect(petWindow.isPanelVisible()).toBe(true);
    const panel = fakeWindows[1] as unknown as FakeWindow;

    petWindow.setPanelOpen(false);
    expect(panel.hide).toHaveBeenCalled();
    expect(petWindow.isPanelVisible()).toBe(false);

    petWindow.setPanelOpen(true);
    petWindow.hide();
    expect(petWindow.isPanelVisible()).toBe(false);
  });
});
