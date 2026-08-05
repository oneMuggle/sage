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

/**
 * Gap D (T1): typed shape of `window.electronAPI.memory`. Each method
 * forwards to its matching snake_case IPC cmd in electron/commands.ts
 * (which translates to a backend route via invoke.ts). The renderer
 * callers (`src/shared/api/memoryClient.ts` / future SettingsMemoryTab)
 * consume this contract — types here, runtime in the `electronAPI.memory`
 * object below.
 *
 * 6 of the 9 backing endpoints already exist (search / save / list /
 * delete / auto_memory get+put). The remaining 3 (findByTurn via
 * {turn_id}, getProfile, getSummary via {session_id}) ship in later
 * tasks; calling them now returns 404 — expected for T1.
 */
type MemoryApi = {
  search: (args: { query: string; type?: string }) => Promise<unknown>;
  save: (args: { content: string; importance?: number; category?: string }) => Promise<unknown>;
  list: (args: { page?: number; page_size?: number; type?: string }) => Promise<unknown>;
  delete: (args: { memory_id: string }) => Promise<unknown>;
  getAutoMemory: () => Promise<unknown>;
  setAutoMemory: (args: { value: boolean }) => Promise<unknown>;
  findByTurn: (args: { turn_id: string }) => Promise<unknown>;
  getProfile: () => Promise<unknown>;
  getSummary: (args: { session_id: string }) => Promise<unknown>;
  /** Task 6 — subscribe to backend memory_written SSE events (via main relay). */
  subscribe: (callback: (event: unknown) => void) => () => void;
};

const electronAPI = {
  /**
   * Renderer-side log bridge — forwards to main process for file persistence.
   * Fire-and-forget on the renderer side; main applies rate limit + writes NDJSON.
   */
  log(
    level: LogLevel,
    msg: string,
    meta?: Record<string, unknown>,
  ): Promise<{ ok: boolean; reason?: string }> {
    return ipcRenderer.invoke('sage:log:write', { level, msg, meta }) as Promise<{
      ok: boolean;
      reason?: string;
    }>;
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
    pickSkillFiles: () => ipcRenderer.invoke('skills:pick-files') as Promise<string[] | null>,
    rescanSkills: () => ipcRenderer.invoke('skills:rescan') as Promise<RescanResult>,
    importSkills: (paths: string[]) =>
      ipcRenderer.invoke('skills:import', paths) as Promise<ImportResult>,
  } satisfies SkillsElectronApiBridge,

  /**
   * Gap D (T1): Memory CRUD + preferences + traceability IPC bridge.
   * Each method translates to the matching snake_case cmd in
   * electron/commands.ts — see MemoryApi type above for param shapes.
   * Post-T1 the renderer wraps these into a typed `memoryClient` (T2),
   * wires settings UI (T5), and exposes profile/summary helpers (T6).
   */
  memory: {
    search: (args: { query: string; type?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_search', args }),
    save: (args: { content: string; importance?: number; category?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_save', args }),
    list: (args: { page?: number; page_size?: number; type?: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_list', args }),
    delete: (args: { memory_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_delete', args }),
    getAutoMemory: () => ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_auto', args: {} }),
    // Backend stores boolean prefs as 'true'/'false' strings (Pydantic str model);
    // stringify here so renderer can pass a real boolean without thinking about it.
    setAutoMemory: (args: { value: boolean }) =>
      ipcRenderer.invoke('sage:invoke', {
        cmd: 'memory_set_auto',
        args: { value: String(args.value) },
      }),
    findByTurn: (args: { turn_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_find_by_turn', args }),
    getProfile: () => ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_profile', args: {} }),
    getSummary: (args: { session_id: string }) =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_summary', args }),
    /**
     * Task 6 — real-time memory events. Asks main to open an EventSource to
     * the backend SSE endpoint, then relays each `sage:memory:event` payload
     * (a JSON string) to the callback. Returns an unsubscribe function that
     * detaches the listener and tells main to close the connection.
     */
    subscribe: (callback: (event: unknown) => void) => {
      ipcRenderer.invoke('sage:memory:subscribe').catch((e) => {
        console.error('[preload] memory subscribe failed:', e);
      });
      const listener = (_e: IpcRendererEvent, data: unknown) => callback(data);
      ipcRenderer.on('sage:memory:event', listener);
      return () => {
        ipcRenderer.off('sage:memory:event', listener);
        ipcRenderer.invoke('sage:memory:unsubscribe').catch(() => undefined);
      };
    },
  } satisfies MemoryApi,

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
