/**
 * Window.electronAPI type augmentation for renderer code.
 *
 * Phase 1 (2026-06-13): stub type; Phase 2 will tighten with proper
 * invoke command names + listen event payloads once Phase 2 IPC mapping
 * is in place.
 *
 * Phase 5 (2026-06-25): added windowControls bridge for custom titlebar.
 *
 * PR-C (2026-07-02): added skills bridge for Rescan + Import buttons.
 */

import type { WindowControlsBridge } from '../api/windowControlsClient';
import type { LogLevel } from '../log/levels';

export type UnlistenFn = () => void;

/** Result returned by `POST /api/v1/skills/rescan` (backend `rescan_skill_mds`). */
export interface RescanResult {
  loaded: Array<{ name: string; source: string; path: string }>;
  skipped: Array<{ name: string; reason: string }>;
  total_loaded: number;
}

/** Result returned by `POST /api/v1/skills/import` (backend `import_skill_mds`). */
export interface ImportResult {
  imported: Array<{ name: string; path: string }>;
  skipped: Array<{ name: string; reason: string }>;
}

/**
 * Shape of `window.electronAPI.skills` — populated by the preload bridge.
 * Three methods back the Skills page Rescan + Import buttons (PR-C).
 */
export interface SkillsElectronApiBridge {
  /** Open native multi-select dialog for SKILL.md files. Returns paths or null on cancel. */
  pickSkillFiles: () => Promise<string[] | null>;
  /** POST /api/v1/skills/rescan — incremental load of new SKILL.md on disk. */
  rescanSkills: () => Promise<RescanResult>;
  /** POST /api/v1/skills/import (multipart FormData) — write + hot-reload selected files. */
  importSkills: (paths: string[]) => Promise<ImportResult>;
}

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  listen<T = unknown>(event: string, handler: (payload: T) => void): Promise<UnlistenFn>;
  windowControls: WindowControlsBridge;
  skills: SkillsElectronApiBridge;
  /** Optional bridge added in Task 8 (renderer→main log IPC). */
  log?: (level: LogLevel, msg: string, meta?: Record<string, unknown>) => Promise<unknown>;
  /** T13 (2026-07-02): Diagnostics card — list log files (newest first). */
  listLogFiles?: () => Promise<
    Array<{ name: string; sizeBytes: number; mtimeMs: number }>
  >;
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
