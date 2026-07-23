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

/**
 * Phase 1.3 (2026-07-16): Office document bridge for the /office page.
 *
 * - pickOfficeFile: native open dialog filtered to .pptx/.docx/.xlsx
 *   → { path, name, sizeBytes } | null
 * - pickSavePath: native save dialog → absolute path | null
 *
 * The 8 read/list/delete HTTP routes (office_ppt_read etc.) are routed
 * through the standard invoke→HTTP path; they don't appear here because
 * they're consumed via the typed `officeApi` wrapper in src/shared/api/officeApi.ts.
 *
 * M0 Task 5 (2026-07-23): added the seven-channel gateway that backs
 * Chat-native CRUD — atomic import via dialog or drag/drop, token-
 * gated complete/discard lifecycle, native Save As, shell.openPath,
 * shell.showItemInFolder. Source paths are NEVER accepted from the
 * renderer; the bridge reconstructs managed paths from
 * `OfficeManagedRef` tuples.
 */

export type OfficeDocType = 'ppt' | 'word' | 'excel';

export interface OfficeManagedRef {
  workspacePath: string;
  docType: OfficeDocType;
  documentId: string;
  filename: string;
}

export interface ImportedOfficeFile extends OfficeManagedRef {
  managedPath: string;
  originalName: string;
  sizeBytes: number;
  importToken: string;
}

export interface PickedOfficeFile {
  path: string;
  name: string;
  sizeBytes: number;
}

export interface SavedOfficeFile {
  savedPath: string;
}

export interface OfficeElectronApiBridge {
  /** Legacy Phase 1.3 channels — kept for compat with the /office page UI. */
  pickOfficeFile: (docType: OfficeDocType) => Promise<PickedOfficeFile | null>;
  pickSavePath: (defaultName: string) => Promise<string | null>;
  /**
   * Open native open dialog filtered by docType → atomic copy into the
   * workspace → return ImportedOfficeFile with an importToken the
   * renderer must later complete or discard. Returns `null` on cancel.
   */
  pickAndImportOfficeFile: (
    workspacePath: string,
    docType: OfficeDocType,
  ) => Promise<ImportedOfficeFile | null>;
  /** Drag/drop variant — renderer already has sourcePath from DataTransfer. */
  importDroppedOfficeFile: (
    workspacePath: string,
    docType: OfficeDocType,
    sourcePath: string,
  ) => Promise<ImportedOfficeFile>;
  /** Finalize an import; the staged file becomes permanent and the token is consumed. */
  completeOfficeImport: (importToken: string) => Promise<void>;
  /** Discard an import; the staged file is deleted. Idempotent on unknown tokens. */
  discardOfficeImport: (importToken: string) => Promise<void>;
  /** Native Save As dialog → copy managed→chosen path. Returns null on cancel. */
  saveOfficeDocumentAs: (ref: OfficeManagedRef) => Promise<SavedOfficeFile | null>;
  /** shell.openPath on the validated managed file. Throws on shell error string. */
  openOfficeDocument: (ref: OfficeManagedRef) => Promise<void>;
  /** shell.showItemInFolder on the validated managed file. */
  showOfficeDocumentInFolder: (ref: OfficeManagedRef) => Promise<void>;
}

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  /**
   * Streaming callers (wiki chat / wiki ingest) pass `options.streamId`
   * so the unlisten payload can abort the in-flight backend fetch via
   * the main process's `streamControllers` Map.
   */
  listen<T = unknown>(
    event: string,
    handler: (payload: T) => void,
    options?: { streamId?: string },
  ): Promise<UnlistenFn>;
  windowControls: WindowControlsBridge;
  skills: SkillsElectronApiBridge;
  office: OfficeElectronApiBridge;
  /**
   * Phase 6 (2026-06-27): Native folder picker (used by LLM Wiki and Office).
   * Returns absolute path string, or null if user cancelled.
   */
  selectDirectory: (opts: {
    intent: 'create' | 'open';
    defaultPath?: string;
  }) => Promise<string | null>;
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
