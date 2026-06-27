import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createWebControlsBridge,
  detectPlatform,
  isElectronDesktop,
  getWindowControlsBridge,
} from '../windowControlsClient';

describe('detectPlatform', () => {
  it('detects macOS from UA', () => {
    const ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36';
    expect(detectPlatform(ua)).toBe('macos');
  });

  it('detects Windows from UA', () => {
    const ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';
    expect(detectPlatform(ua)).toBe('windows');
  });

  it('detects Linux from UA', () => {
    const ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36';
    expect(detectPlatform(ua)).toBe('linux');
  });

  it('falls back to web for unknown UA', () => {
    expect(detectPlatform('SomeRandomBot/1.0')).toBe('web');
    expect(detectPlatform('')).toBe('web');
  });

  it('uses navigator.userAgent when no argument provided', () => {
    // jsdom environment has navigator defined
    const result = detectPlatform();
    // In test environment, should return 'web' or detect from jsdom UA
    expect(typeof result).toBe('string');
    expect(['macos', 'windows', 'linux', 'web']).toContain(result);
  });
});

describe('isElectronDesktop', () => {
  it('returns true for macos/windows/linux', () => {
    expect(isElectronDesktop('macos')).toBe(true);
    expect(isElectronDesktop('windows')).toBe(true);
    expect(isElectronDesktop('linux')).toBe(true);
  });

  it('returns false for web', () => {
    expect(isElectronDesktop('web')).toBe(false);
  });
});

describe('createWebControlsBridge', () => {
  it('capturePage rejects with Not in desktop', async () => {
    const bridge = createWebControlsBridge();
    await expect(bridge.capturePage()).rejects.toThrow('Not in desktop');
  });

  it('minimize/toggleMaximize/close resolve without error', async () => {
    const bridge = createWebControlsBridge();
    await expect(bridge.minimize()).resolves.toBeUndefined();
    await expect(bridge.toggleMaximize()).resolves.toBeUndefined();
    await expect(bridge.close()).resolves.toBeUndefined();
  });

  it('isMaximized resolves to false', async () => {
    const bridge = createWebControlsBridge();
    await expect(bridge.isMaximized()).resolves.toBe(false);
  });

  it('has all required methods', () => {
    const bridge = createWebControlsBridge();
    expect(typeof bridge.minimize).toBe('function');
    expect(typeof bridge.toggleMaximize).toBe('function');
    expect(typeof bridge.close).toBe('function');
    expect(typeof bridge.capturePage).toBe('function');
    expect(typeof bridge.isMaximized).toBe('function');
  });
});

describe('getWindowControlsBridge', () => {
  let originalWindow: typeof globalThis.window;

  beforeEach(() => {
    originalWindow = globalThis.window;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // Restore window state
    if (originalWindow) {
      globalThis.window = originalWindow;
    }
  });

  it('returns null when window is undefined', () => {
    delete (globalThis as { window?: typeof globalThis.window }).window;
    expect(getWindowControlsBridge()).toBeNull();
  });

  it('returns null when electronAPI is undefined', () => {
    (window as { electronAPI?: unknown }).electronAPI = undefined;
    expect(getWindowControlsBridge()).toBeNull();
  });

  it('returns null when windowControls is undefined', () => {
    (window as { electronAPI?: unknown }).electronAPI = {};
    expect(getWindowControlsBridge()).toBeNull();
  });

  it('returns electronAPI.windowControls when available', () => {
    const mockBridge = createWebControlsBridge();
    (window as { electronAPI?: unknown }).electronAPI = { windowControls: mockBridge };
    expect(getWindowControlsBridge()).toBe(mockBridge);
  });

  it('returns electronAPI.windowControls even on Linux UA', () => {
    const mockBridge = createWebControlsBridge();
    (window as { electronAPI?: unknown }).electronAPI = { windowControls: mockBridge };
    // UA doesn't matter - if electronAPI exists, use it
    expect(getWindowControlsBridge()).toBe(mockBridge);
  });
});

describe('windowControls singleton', () => {
  it('uses electronAPI.windowControls when available', async () => {
    const mockMinimize = vi.fn().mockResolvedValue(undefined);
    (window as { electronAPI?: unknown }).electronAPI = {
      windowControls: {
        minimize: mockMinimize,
        toggleMaximize: vi.fn(),
        close: vi.fn(),
        capturePage: vi.fn(),
        isMaximized: vi.fn(),
      },
    };

    // Re-import to get fresh singleton
    vi.resetModules();
    const { windowControls: freshSingleton } = await import('../windowControlsClient');

    await freshSingleton.minimize();
    expect(mockMinimize).toHaveBeenCalled();
  });

  it('falls back to web stub when electronAPI unavailable', async () => {
    (window as { electronAPI?: unknown }).electronAPI = undefined;

    vi.resetModules();
    const { windowControls: freshSingleton } = await import('../windowControlsClient');

    // Web stub methods resolve silently
    await expect(freshSingleton.minimize()).resolves.toBeUndefined();
    await expect(freshSingleton.isMaximized()).resolves.toBe(false);
    // capturePage rejects in web mode
    await expect(freshSingleton.capturePage()).rejects.toThrow('Not in desktop');
  });
});
