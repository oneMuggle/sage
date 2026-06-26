"use strict";
/**
 * windowControlsClient — IPC client + platform detection for window controls.
 *
 * Phase 5: Provides platform detection (macOS / Windows / Linux / Web) and
 * a WindowControlsBridge abstraction that can be backed by Electron IPC
 * (in desktop mode) or a no-op stub (in web mode).
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.windowControls = void 0;
exports.detectPlatform = detectPlatform;
exports.isElectronDesktop = isElectronDesktop;
exports.createWebControlsBridge = createWebControlsBridge;
exports.getWindowControlsBridge = getWindowControlsBridge;
/** UA patterns for platform detection (table-driven). */
const UA_PATTERNS = [
    { pattern: /Macintosh|Mac OS X/i, platform: 'macos' },
    { pattern: /Windows NT/i, platform: 'windows' },
    { pattern: /Linux/i, platform: 'linux' },
];
/**
 * Detect platform from user agent string.
 * Defaults to current navigator.userAgent if available.
 */
function detectPlatform(ua = typeof navigator !== 'undefined' ? navigator.userAgent : '') {
    for (const { pattern, platform } of UA_PATTERNS) {
        if (pattern.test(ua))
            return platform;
    }
    return 'web';
}
/** Whether the platform represents a desktop Electron environment. */
function isElectronDesktop(platform) {
    return platform === 'macos' || platform === 'windows' || platform === 'linux';
}
/**
 * Create a stub bridge for web mode.
 * All operations resolve silently; capturePage rejects (no screen capture in web).
 */
function createWebControlsBridge() {
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
function getWindowControlsBridge() {
    if (typeof window === 'undefined')
        return null;
    return window.electronAPI?.windowControls ?? null;
}
/**
 * Singleton bridge instance.
 * Uses electronAPI.windowControls in desktop mode, falls back to web stub.
 */
exports.windowControls = typeof window !== 'undefined' && window.electronAPI?.windowControls
    ? window.electronAPI.windowControls
    : createWebControlsBridge();
//# sourceMappingURL=windowControlsClient.js.map