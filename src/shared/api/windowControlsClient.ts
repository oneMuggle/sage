/**
 * windowControlsClient — IPC client + platform detection for window controls.
 *
 * Phase 5: Provides platform detection (macOS / Windows / Linux / Web) and
 * a WindowControlsBridge abstraction that can be backed by Electron IPC
 * (in desktop mode) or a no-op stub (in web mode).
 */

export type Platform = 'macos' | 'windows' | 'linux' | 'web';

/**
 * Bridge interface for window control operations.
 * In Electron desktop mode, backed by IPC to main process.
 * In web mode, operations are no-ops (capturePage rejects).
 */
export interface WindowControlsBridge {
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  close(): Promise<void>;
  /** Returns base64 PNG string (no data URI prefix). */
  capturePage(): Promise<string>;
  isMaximized(): Promise<boolean>;
}

/** UA patterns for platform detection (table-driven). */
const UA_PATTERNS: Array<{ pattern: RegExp; platform: Platform }> = [
  { pattern: /Macintosh|Mac OS X/i, platform: 'macos' },
  { pattern: /Windows NT/i, platform: 'windows' },
  { pattern: /Linux/i, platform: 'linux' },
];

/**
 * Detect platform from user agent string.
 * Defaults to current navigator.userAgent if available.
 */
export function detectPlatform(
  ua: string = typeof navigator !== 'undefined' ? navigator.userAgent : '',
): Platform {
  for (const { pattern, platform } of UA_PATTERNS) {
    if (pattern.test(ua)) return platform;
  }
  return 'web';
}

/** Whether the platform represents a desktop Electron environment. */
export function isElectronDesktop(platform: Platform): boolean {
  return platform === 'macos' || platform === 'windows' || platform === 'linux';
}

/**
 * Create a stub bridge for web mode.
 * All operations resolve silently; capturePage rejects (no screen capture in web).
 */
export function createWebControlsBridge(): WindowControlsBridge {
  return {
    minimize: () => Promise.resolve(),
    toggleMaximize: () => Promise.resolve(),
    close: () => Promise.resolve(),
    capturePage: () => Promise.reject(new Error('Not in desktop')),
    isMaximized: () => Promise.resolve(false),
  };
}

/**
 * Get the window controls bridge from electronAPI (if available).
 * Returns null in web mode or when electronAPI is not present.
 */
export function getWindowControlsBridge(): WindowControlsBridge | null {
  if (typeof window === 'undefined') return null;
  return window.electronAPI?.windowControls ?? null;
}

/**
 * Singleton bridge instance.
 * Uses electronAPI.windowControls in desktop mode, falls back to web stub.
 */
export const windowControls: WindowControlsBridge =
  typeof window !== 'undefined' && window.electronAPI?.windowControls
    ? window.electronAPI.windowControls
    : createWebControlsBridge();
