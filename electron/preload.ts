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
  DiagnosticElectronApiBridge,
  ImportResult,
  JournalElectronApiBridge,
  ProvidersElectronApiBridge,
  RescanResult,
  SkillsElectronApiBridge,
  UpdateElectronApiBridge,
} from '../src/shared/types/electron-api';
import type {
  JournalFillFromContentRequest,
  JournalFillFromContentResponse,
  JournalGetSpecResponse,
  JournalListSpecsResponse,
  JournalParseTemplateResponse,
  JournalValidateResponse,
} from '../src/shared/api/types';
import type { CheckResult } from './updateManager';
import type { UpdateStateChangedEvent } from './updateIpc';
import type { UpdateChannel, UpdateConfig, UpdateStrategy } from './updateConfig';
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
  /** Important-2 — independent "记忆检索注入" preference (GET/PUT
   *  /api/v1/preferences/memory_retrieval). Independent of auto_memory. */
  getMemoryRetrieval: () => Promise<unknown>;
  setMemoryRetrieval: (args: { value: boolean }) => Promise<unknown>;
  findByTurn: (args: { turn_id: string }) => Promise<unknown>;
  getProfile: () => Promise<unknown>;
  getSummary: (args: { session_id: string }) => Promise<unknown>;
  /** Task 6 — subscribe to backend memory_written SSE events (via main relay).
   *  Resolves to an unsubscribe function, or `null` when the main relay could
   *  not be established (renderer should fall back to polling). */
  subscribe: (callback: (event: unknown) => void) => Promise<(() => void) | null>;
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

  /** Authenticated raw backend relay; the local capability stays in main. */
  backendRequest<T>(request: {
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    path: string;
    headers?: Record<string, string>;
    body?: unknown;
    timeoutMs?: number;
    responseType?: 'json' | 'arraybuffer';
  }): Promise<T> {
    return ipcRenderer.invoke('sage:backend-request', request) as Promise<T>;
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
   * live-events P1 附带 (2026-09-07): 审批等待 OS 通知。main 进程经
   * Electron Notification 弹系统通知; 点击聚焦窗口。不支持的平台
   * （Win7 老系统）返回 {ok:false, reason:'unsupported'} 静默降级。
   */
  notifyApproval: (payload: { title?: string; body?: string }) =>
    ipcRenderer.invoke('sage:notify:approval', payload) as Promise<{
      ok: boolean;
      reason?: string;
    }>,

  /**
   * S8 (round4): 分会话 OS 通知。Renderer 判定"该不该打扰"后触发;
   * 原生 Notification 展示与点击聚焦在 main('sage:session:notify')。
   */
  notifySession: (payload: { sessionId: string; title: string; body: string }) =>
    ipcRenderer.invoke('sage:session:notify', payload) as Promise<{ shown: boolean }>,

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
    importSkills: () => ipcRenderer.invoke('skills:import') as Promise<ImportResult>,
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
    getMemoryRetrieval: () =>
      ipcRenderer.invoke('sage:invoke', { cmd: 'memory_get_retrieval', args: {} }),
    setMemoryRetrieval: (args: { value: boolean }) =>
      ipcRenderer.invoke('sage:invoke', {
        cmd: 'memory_set_retrieval',
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
     * (a JSON string) to the callback. Returns an unsubscribe function, or
     * `null` if the main relay could not be established (invoke rejected or
     * main reported { subscribed: false }) — the renderer must fall back to
     * polling in that case instead of silently dead-airing.
     */
    subscribe: async (callback: (event: unknown) => void) => {
      let result: { subscribed?: boolean; error?: string } | undefined;
      try {
        result = (await ipcRenderer.invoke('sage:memory:subscribe')) as {
          subscribed?: boolean;
          error?: string;
        };
      } catch (e) {
        console.error('[preload] memory subscribe failed:', e);
        return null;
      }
      if (!result?.subscribed) {
        console.warn('[preload] memory subscribe unavailable:', result?.error ?? 'unknown');
        return null;
      }
      const listener = (_e: IpcRendererEvent, data: unknown) => callback(data);
      ipcRenderer.on('sage:memory:event', listener);
      return () => {
        ipcRenderer.off('sage:memory:event', listener);
        ipcRenderer.invoke('sage:memory:unsubscribe').catch(() => undefined);
      };
    },
  } satisfies MemoryApi,

  /**
   * Media bridge (Phase 2, 2026-09-12): multipart upload for chat attachments
   * and binary media fetching for TTS/ASR/image generation.
   */
  media: {
    uploadAttachment: (buffer: ArrayBuffer, filename: string, contentType: string) =>
      ipcRenderer.invoke('media:upload-attachment', { buffer, filename, contentType }) as Promise<{
        media_ref: unknown;
        api_url: string;
      }>,
    getMediaBlobUrl: (apiUrl: string) =>
      ipcRenderer.invoke('sage:backend-request', {
        method: 'GET',
        path: apiUrl,
        responseType: 'arraybuffer',
      }) as Promise<ArrayBuffer>,
  },

  /**
   * Journal template bridge (Task 7, 2026-09-10): parses .doc/.docx
   * journal templates into structured JournalSpec, lists saved specs,
   * fetches one by id, validates existing papers against a spec, and
   * fills papers from structured content. LLM tool wiring is handled
   * separately via chat-driven `office_journal_generate_article`.
   */
  journal: {
    parseTemplate: (filePath: string) =>
      ipcRenderer.invoke('office_journal_parse_template', {
        file_path: filePath,
      }) as Promise<JournalParseTemplateResponse>,
    listSpecs: () =>
      ipcRenderer.invoke('office_journal_list_specs', {}) as Promise<JournalListSpecsResponse>,
    getSpec: (specId: string) =>
      ipcRenderer.invoke('office_journal_get_spec', {
        spec_id: specId,
      }) as Promise<JournalGetSpecResponse>,
    validate: (args: { spec_id?: string; file_path?: string }) =>
      ipcRenderer.invoke('office_journal_validate', args) as Promise<JournalValidateResponse>,
    fillFromContent: (req: JournalFillFromContentRequest) =>
      ipcRenderer.invoke(
        'office_journal_fill_from_content',
        req,
      ) as Promise<JournalFillFromContentResponse>,
  } satisfies JournalElectronApiBridge,

  updates: {
    check: () => ipcRenderer.invoke('update:check') as Promise<CheckResult>,
    download: () => ipcRenderer.invoke('update:download') as Promise<void>,
    install: () => ipcRenderer.invoke('update:install') as Promise<void>,
    rollback: (reason?: string) => ipcRenderer.invoke('update:rollback', reason) as Promise<void>,
    canRollback: () =>
      ipcRenderer.invoke('update:can-rollback') as Promise<{ allowed: boolean; reason?: string }>,
    setStrategy: (strategy: UpdateStrategy) =>
      ipcRenderer.invoke('update:set-strategy', strategy) as Promise<void>,
    getConfig: () => ipcRenderer.invoke('update:get-config') as Promise<UpdateConfig>,
    setChannel: (channel: UpdateChannel) =>
      ipcRenderer.invoke('update:set-channel', channel) as Promise<void>,
    checkWith: (providerId: string, channel?: string) =>
      ipcRenderer.invoke('update:check-with', {
        providerId,
        channel,
      }) as Promise<CheckResult | null>,
    onStateChanged: (handler: (payload: UpdateStateChangedEvent) => void): UnlistenFn => {
      const listener = (_event: IpcRendererEvent, payload: UpdateStateChangedEvent) =>
        handler(payload);
      ipcRenderer.on('update:state-changed', listener);
      return () => ipcRenderer.off('update:state-changed', listener);
    },
  } satisfies UpdateElectronApiBridge,

  /**
   * Phase 2 (2026-09-10): Provider management bridge for the Settings UI.
   * Token fields are masked in IPC responses by providerIpc.maskToken(); the
   * renderer therefore sees `config.token: '***masked***'` when present.
   *
   * Channels wired in electron/update/providerIpc.ts:
   *   provider:list, provider:get, provider:add, provider:update,
   *   provider:remove, provider:set-default, provider:test
   */
  providers: {
    list: () =>
      ipcRenderer.invoke('provider:list') as Promise<
        Array<{
          id: string;
          type: 'github' | 'gitee' | 'gitlab' | 'generic-http';
          displayName: string;
          enabled: boolean;
          isDefault: boolean;
          config: Record<string, unknown>;
        }>
      >,
    get: (id: string) =>
      ipcRenderer.invoke('provider:get', { id }) as Promise<{
        id: string;
        type: 'github' | 'gitee' | 'gitlab' | 'generic-http';
        displayName: string;
        enabled: boolean;
        isDefault: boolean;
        config: Record<string, unknown>;
      } | null>,
    add: (cfg: {
      type: 'github' | 'gitee' | 'gitlab' | 'generic-http';
      displayName: string;
      enabled: boolean;
      isDefault: boolean;
      config: Record<string, unknown>;
    }) => ipcRenderer.invoke('provider:add', cfg) as Promise<{ id: string }>,
    update: (
      id: string,
      patch: Partial<{
        displayName: string;
        enabled: boolean;
        isDefault: boolean;
        config: Record<string, unknown>;
      }>,
    ) => ipcRenderer.invoke('provider:update', { id, patch }) as Promise<{ ok: boolean }>,
    remove: (id: string) =>
      ipcRenderer.invoke('provider:remove', { id }) as Promise<{ ok: boolean }>,
    setDefault: (id: string) =>
      ipcRenderer.invoke('provider:set-default', { id }) as Promise<{ ok: boolean }>,
    test: (id: string) =>
      ipcRenderer.invoke('provider:test', { id }) as Promise<{
        ok: boolean;
        latencyMs: number;
        error?: string;
      }>,
  } satisfies ProvidersElectronApiBridge,

  /**
   * Task 10 (2026-09-11): Diagnostic export bridge for LLM trace bundles.
   *
   * - exportBundle: opens native save dialog, writes a zip archive with
   *   LLM request/response traces + system metadata. Resolves to
   *   { ok: true, path } on success or { ok: false, code, error } on failure.
   * - preview: returns a summary of the trace dataset (count, timestamp
   *   range, sample URLs, format version) without triggering export.
   *
   * Backed by `diagnostic:export` and `diagnostic:preview` IPC channels
   * registered in electron/main.ts.
   */
  diagnostic: {
    exportBundle: (opts: { includePrompts: boolean; includeHostname: boolean }) =>
      ipcRenderer.invoke('diagnostic:export', opts) as Promise<
        { ok: true; path: string } | { ok: false; code: string; error: string }
      >,
    preview: () =>
      ipcRenderer.invoke('diagnostic:preview') as Promise<{
        count: number;
        oldestTs: string | null;
        newestTs: string | null;
        sampleUrls: string[];
        version: string;
      }>,
  } satisfies DiagnosticElectronApiBridge,

  /**
   * T13 (2026-07-02): Log management bridge — Diagnostics card on Settings page.
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

  /**
   * Demo mode toggle (2026-08-27): 用户在 Settings → 通用 开关调用.
   * 写入 <userData>/sage-demo-mode.json, 下次启动 main 进程时读取生效.
   * 返回 { ok: boolean, error?: string } — 失败时由 renderer 决定是否 toast.
   */
  resetDemoMode(): Promise<{ ok: boolean; error?: string }> {
    return ipcRenderer.invoke('sage:demo-mode:set', { demoMode: false }) as Promise<{
      ok: boolean;
      error?: string;
    }>;
  },

  setDemoMode(demoMode: boolean): Promise<{ ok: boolean; error?: string }> {
    return ipcRenderer.invoke('sage:demo-mode:set', { demoMode }) as Promise<{
      ok: boolean;
      error?: string;
    }>;
  },

  /** E-2 (round5 批次 C/E): 读取「关闭即隐藏到托盘」偏好。 */
  getCloseToTray(): Promise<{ enabled: boolean }> {
    return ipcRenderer.invoke('sage:close-to-tray:get') as Promise<{ enabled: boolean }>;
  },

  /** E-2: 写入「关闭即隐藏到托盘」偏好。 */
  setCloseToTray(enabled: boolean): Promise<{ ok: boolean; enabled: boolean }> {
    return ipcRenderer.invoke('sage:close-to-tray:set', { enabled }) as Promise<{
      ok: boolean;
      enabled: boolean;
    }>;
  },

  /**
   * 演示模式同步标志 (2026-08-27): main 进程在演示模式激活时经
   * webPreferences.additionalArguments 注入 --sage-demo-mode=1。
   * renderer 的 isDemoMode() 优先读它 — settings store 在首屏请求时尚未
   * 从存储加载完成, 只读 store 会竞态漏拦截。
   */
  demoMode: process.argv.includes('--sage-demo-mode=1'),

  /**
   * P2-3.11 (2026-09-13): Artifacts 独立窗口。
   * 双击 Artifact → 弹出独立 BrowserWindow 展示 HTML 内容。
   * 仅支持 kind === 'html';其他类型返回 {ok:false, reason:'unsupported'}。
   */
  openArtifactWindow: (artifact: { id: string; name: string; kind: string; path: string }) =>
    ipcRenderer.invoke('sage:artifact-window:open', artifact) as Promise<{
      ok: boolean;
      reason?: string;
    }>,
};

contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type augmentation for the renderer side (auto-imported by src/lib/electronApi.d.ts)
export type ElectronAPI = typeof electronAPI;
