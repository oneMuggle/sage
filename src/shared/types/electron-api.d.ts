/**
 * Window.electronAPI type augmentation for renderer code.
 *
 * Phase 1 (2026-06-13): stub type; Phase 2 will tighten with proper
 * invoke command names + listen event payloads once Phase 2 IPC mapping
 * is in place.
 *
 * Phase 5 (2026-06-25): added windowControls bridge for custom titlebar.
 */

import type { WindowControlsBridge } from '../api/windowControlsClient';
import type { LogLevel } from '../log/levels';

export type UnlistenFn = () => void;

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  listen<T = unknown>(event: string, handler: (payload: T) => void): Promise<UnlistenFn>;
  windowControls: WindowControlsBridge;
  /** Optional bridge added in Task 8 (renderer→main log IPC). */
  log?: (level: LogLevel, msg: string, meta?: Record<string, unknown>) => Promise<unknown>;
  /** T13 (2026-07-02): Diagnostics card — list log files (newest first). */
  listLogFiles?: () => Promise<Array<{ name: string; sizeBytes: number; mtimeMs: number }>>;
  /** T13: Open the OS file manager at the log directory. Returns the resolved dir path. */
  openLogDir?: () => Promise<string>;
  /** T13: Copy the log directory path to the clipboard. Returns the resolved dir path. */
  copyLogPath?: () => Promise<string>;
  /** T13: Remove log files older than 7 days. Returns count removed. */
  cleanupLogs?: () => Promise<{ removed: number }>;
  /** T13: Update SAGE_LOG_LEVEL for the main process logger. */
  setLogLevel?: (level: LogLevel) => Promise<{ ok: true }>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
