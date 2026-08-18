import { BrowserWindow } from 'electron';

/**
 * Module-level singleton for the main BrowserWindow.
 *
 * Extracted from `electron/main.ts` so unit tests can mock it (vi.mock).
 * The previous `let mainWindow = null` in main.ts was unreplaceable from a
 * vitest harness without touching the production source.
 */
export let mainWindow: BrowserWindow | null = null;

export function setMainWindow(win: BrowserWindow | null): void {
  mainWindow = win;
}