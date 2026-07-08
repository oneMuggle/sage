/**
 * Electron preload script — bridges main ↔ renderer with contextIsolation.
 *
 * Exposes `window.electronAPI` to the React frontend via contextBridge,
 * matching the shape frontend code expects from Tauri (invoke + listen).
 *
 * Phase 1 (2026-06-13):
 *   - invoke(cmd, args) → ipcRenderer.invoke('sage:invoke', { cmd, args })
 *   - listen(event, handler) → ipcRenderer.invoke('sage:listen', { event })
 *                              (Phase 2 will replace with proper on/off relay)
 *
 * Security:
 *   - contextIsolation: true  (this preload runs in isolated world)
 *   - nodeIntegration: false  (renderer is plain web page)
 *   - sandbox: false          (Phase 3 Win7 tradeoff; SUID sandbox helper
 *                              unavailable on Win7 without UAC workaround)
 */
import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';
import type { WindowControlsBridge } from '../src/shared/api/windowControlsClient';
import type {
  ImportResult,
  RescanResult,
  SkillsElectronApiBridge,
} from '../src/shared/types/electron-api';
import type { LogLevel } from '../src/shared/log/levels';

/** UnlistenFn signature mirrors Tauri 2.x for drop-in Phase 2 compatibility. */
export type UnlistenFn = () => void;

const electronAPI = {
  /**
   * Renderer-side log bridge — forwards to main process for file persistence.
   * Fire-and-forget on the renderer side; main applies rate limit + writes NDJSON.
   */
  log(level: LogLevel, msg: string, meta?: Record<string, unknown>): Promise<{ ok: boolean; reason?: string }> {
    return ipcRenderer.invoke('sage:log:write', { level, msg, meta }) as Promise<{ ok: boolean; reason?: string }>;
  },

  /**
   * Frontend invoke shim — matches `@tauri-apps/api/core` invoke<T>() signature.
   * Phase 2 will replace this entirely; for now it routes through main process.
   */
  invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
    return ipcRenderer.invoke('sage:invoke', { cmd, args: args ?? {} }) as Promise<T>;
  },

  /**
   * Frontend listen shim — matches `@tauri-apps/api/event` listen<T>() signature.
   *
   * Phase 2 wiring:
   *   1. call ipcRenderer.invoke('sage:listen', { event }) to subscribe in main;
   *      main opens backend NDJSON relay and pushes events via webContents.send
   *   2. receive payloads via ipcRenderer.on(`sage:event:${event}`, (_e, payload) => handler(payload))
   *   3. unlisten() invokes sage:unlisten to abort backend relay + remove listener
   *
   * Streaming callers (e.g. wikiChatStream in api-client/wiki.ts) pass
   * `options.streamId` so the unlisten payload can abort the in-flight
   * backend fetch via the main process's `streamControllers` Map.
   */
  listen<T>(
    event: string,
    handler: (payload: T) => void,
    options?: { streamId?: string },
  ): Promise<UnlistenFn> {
    // Forward subscription request to main; main opens backend relay
    ipcRenderer
      .invoke('sage:listen', { event })
      .catch((e) => console.error(`[preload] listen(${event}) failed:`, e));
    // Local listener so renderer receives relayed events
    const wrapped = (_e: IpcRendererEvent, payload: T) => handler(payload);
    ipcRenderer.on(`sage:event:${event}`, wrapped);
    const unlisten: UnlistenFn = () => {
      ipcRenderer.off(`sage:event:${event}`, wrapped);
      ipcRenderer
        .invoke('sage:unlisten', { event, streamId: options?.streamId })
        .catch(() => undefined);
    };
    return Promise.resolve(unlisten);
  },

  /**
   * Phase 5: Window controls bridge for custom titlebar.
   * Delegates to main process IPC handlers (sage:window-controls:*).
   */
  windowControls: {
    minimize: () => ipcRenderer.invoke('sage:window-controls:minimize'),
    toggleMaximize: () => ipcRenderer.invoke('sage:window-controls:toggle-maximize'),
    close: () => ipcRenderer.invoke('sage:window-controls:close'),
    capturePage: () => ipcRenderer.invoke('sage:window-controls:capture-page') as Promise<string>,
    isMaximized: () => ipcRenderer.invoke('sage:window-controls:is-maximized') as Promise<boolean>,
  } satisfies WindowControlsBridge,

  /**
   * Phase 6 (2026-06-27): Native folder picker for LLM Wiki.
   * Returns absolute path string, or null if user cancelled.
   */
  selectDirectory: (opts: { intent: 'create' | 'open'; defaultPath?: string }) =>
    ipcRenderer.invoke('sage:dialog:select-directory', opts) as Promise<string | null>,

  /**
   * PR-C (2026-07-02): Skills load-new bridge.
   * - pickSkillFiles: native multi-select dialog → string[] | null
   * - rescanSkills: POST /api/v1/skills/rescan → RescanResult
   * - importSkills: POST /api/v1/skills/import (multipart) → ImportResult
   *
   * Nested under `skills` (mirrors `windowControls` pattern) so future
   * skills IPC additions group naturally without polluting top-level.
   */
  skills: {
    pickSkillFiles: () =>
      ipcRenderer.invoke('skills:pick-files') as Promise<string[] | null>,
    rescanSkills: () =>
      ipcRenderer.invoke('skills:rescan') as Promise<RescanResult>,
    importSkills: (paths: string[]) =>
      ipcRenderer.invoke('skills:import', paths) as Promise<ImportResult>,
  } satisfies SkillsElectronApiBridge,

  /**
   * T13 (2026-07-02): Log management bridge — Diagnostics card on Settings page.
   * - listLogFiles: scan log dir → [{ name, sizeBytes, mtimeMs }] sorted newest first
   * - openLogDir: shell.openPath() + return resolved dir
   * - copyLogPath: clipboard.writeText() + return resolved dir
   * - cleanupLogs: rotate + unlink files older than 7 days → { removed }
   * - setLogLevel: update process.env.SAGE_LOG_LEVEL → { ok: true }
   */
  listLogFiles(): Promise<Array<{ name: string; sizeBytes: number; mtimeMs: number }>> {
    return ipcRenderer.invoke('sage:log:list-files') as Promise<
      Array<{ name: string; sizeBytes: number; mtimeMs: number }>
    >;
  },
  openLogDir(): Promise<string> {
    return ipcRenderer.invoke('sage:log:open-dir') as Promise<string>;
  },
  copyLogPath(): Promise<string> {
    return ipcRenderer.invoke('sage:log:copy-path') as Promise<string>;
  },
  cleanupLogs(): Promise<{ removed: number }> {
    return ipcRenderer.invoke('sage:log:cleanup') as Promise<{ removed: number }>;
  },
  setLogLevel(level: LogLevel): Promise<{ ok: true }> {
    return ipcRenderer.invoke('sage:log:set-level', { level }) as Promise<{ ok: true }>;
  },
};

contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type augmentation for the renderer side (auto-imported by src/lib/electronApi.d.ts)
export type ElectronAPI = typeof electronAPI;
