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

import type { UpdateChannel, UpdateConfig, UpdateStrategy } from '../../../electron/updateConfig';
import type { UpdateStateChangedEvent } from '../../../electron/updateIpc';
import type { CheckResult } from '../../../electron/updateManager';
import type { RemoteMcpElectronApiBridge } from '../api/remoteMcpApi';
import type {
  JournalFillFromContentRequest,
  JournalFillFromContentResponse,
  JournalGetSpecResponse,
  JournalListSpecsResponse,
  JournalParseTemplateResponse,
  JournalValidateResponse,
} from '../api/types';
import type { WindowControlsBridge } from '../api/windowControlsClient';
import type { LogLevel } from '../log/levels';

export type UnlistenFn = () => void;

export interface BrowserPanelElectronApiBridge {
  show(): Promise<{ ok: boolean }>;
  hide(): Promise<{ ok: boolean }>;
  setBounds(rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  }): Promise<{ ok: boolean }>;
  navigate(url: string): Promise<{ ok: boolean }>;
  back(): Promise<{ ok: boolean }>;
  forward(): Promise<{ ok: boolean }>;
  reload(): Promise<{ ok: boolean }>;
  current(): Promise<{
    url: string;
    title: string;
    canGoBack: boolean;
    canGoForward: boolean;
  }>;
}

export interface MemoryElectronApiBridge {
  list: (args?: Record<string, unknown>) => Promise<unknown>;
  search: (args: Record<string, unknown>) => Promise<unknown>;
  save: (args: Record<string, unknown>) => Promise<unknown>;
  delete: (args: Record<string, unknown>) => Promise<unknown>;
  getProfile: () => Promise<unknown>;
  diagnostics: () => Promise<unknown>;
  createProfile: (args: Record<string, unknown>) => Promise<unknown>;
  updateProfile: (args: Record<string, unknown>) => Promise<unknown>;
  deleteProfile: (args: Record<string, unknown>) => Promise<unknown>;
  getSummary: (args: Record<string, unknown>) => Promise<unknown>;
  getRecentWrites: (args: Record<string, unknown>) => Promise<unknown>;
  undoWrite: (args: Record<string, unknown>) => Promise<unknown>;
}

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
 * Arena token window status (P3, plan §5.9) — mirrors the controller's
 * status() payload; `window.electronAPI.arenaToken.status()` resolves to it.
 */
export interface ArenaTokenStatus {
  running: boolean;
  ready: boolean;
  count: number;
  error: string;
  exitIp: string;
  ua: string;
  uptimeMs: number;
  proxyUrl: string;
  lastPushAgeMs: number | null;
}

/**
 * Shape of `window.electronAPI.arenaToken` — populated by the preload bridge.
 * Backs the Arena DrawTab token-window status card (plan §5.9/§6.2, P3).
 */
export interface ArenaTokenElectronApiBridge {
  /** Current token-window status (window may not be running). */
  status: () => Promise<ArenaTokenStatus>;
  /** Open the hidden window, wait for readiness, warmup-mint, start polling. */
  start: () => Promise<void>;
  /** Destroy the window and stop polling (idempotent). */
  stop: () => Promise<void>;
  /** ensure_alive semantics: reload the page when grecaptcha dropped. */
  reload: () => Promise<boolean>;
  /** Manual proxy override; null reverts to the system proxy. */
  pickProxy: (proxyUrl: string | null) => Promise<void>;
}

/**
 * Shape of `window.electronAPI.skills` — populated by the preload bridge.
 * Five methods back the Skills page Rescan + Import + Import-directory buttons (PR-C + T-4b).
 */
export interface SkillsElectronApiBridge {
  /** Open native multi-select dialog for SKILL.md files. Returns paths or null on cancel. */
  pickSkillFiles: () => Promise<string[] | null>;
  /** POST /api/v1/skills/rescan — incremental load of new SKILL.md on disk. */
  rescanSkills: () => Promise<RescanResult>;
  /** POST /api/v1/skills/import (multipart FormData) — write + hot-reload selected files. */
  importSkills: () => Promise<ImportResult>;
  /** T-4b: Open native directory picker. Returns realpath or null on cancel. */
  pickSkillDirectory: () => Promise<string | null>;
  /** T-4b: POST /api/v1/skills/import-directory — walk + multipart with posix relative paths.
   *  `pickedPath` 必须与上一次 pick 返回的路径一致（主进程会比对 recentPickedDirectory）；
   *  不一致 → 抛出「directory selection changed, please pick again」。 */
  importSkillDirectory: (pickedPath: string) => Promise<ImportResult>;
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

export type OfficeDocType = 'ppt' | 'word' | 'excel' | 'pdf';

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

export type OfficeStagingStatus =
  | 'completed'
  | 'active'
  | 'recent'
  | 'review'
  | 'untracked'
  | 'unreadable';
export interface OfficeStagingReport {
  readOnly: true;
  truncated: boolean;
  items: Array<{
    documentId: string;
    docType: OfficeDocType;
    status: OfficeStagingStatus;
    createdAt?: number;
  }>;
}

export interface OfficeElectronApiBridge {
  /** Read-only evidence, not deletion authorization; optional for old desktop builds. */
  previewStaging?: (workspacePath: string) => Promise<OfficeStagingReport>;
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
  /**
   * Deprecated no-op. Renderer document lists cannot establish orphanhood.
   * Always returns swept=0; use previewStaging for read-only evidence.
   */
  sweepOrphanStaging: (opts: {
    workspacePath: string;
    knownDocIds: string[];
  }) => Promise<{ swept: number }>;
  /** Native Save As dialog → copy managed→chosen path. Returns null on cancel. */
  saveOfficeDocumentAs: (ref: OfficeManagedRef) => Promise<SavedOfficeFile | null>;
  /** shell.openPath on the validated managed file. Throws on shell error string. */
  openOfficeDocument: (ref: OfficeManagedRef) => Promise<void>;
  /** shell.showItemInFolder on the validated managed file. */
  showOfficeDocumentInFolder: (ref: OfficeManagedRef) => Promise<void>;
}

/**
 * Media bridge (Phase 2, 2026-09-12): multipart upload for chat attachments
 * and binary media fetching for TTS/ASR/image generation.
 */
export interface MediaElectronApiBridge {
  /** Upload audio file as multipart/form-data to /api/v1/chat/attachments */
  uploadAttachment: (
    buffer: ArrayBuffer,
    filename: string,
    contentType: string,
  ) => Promise<{ media_ref: unknown; api_url: string }>;
  /** Fetch media file as ArrayBuffer via sage:backend-request */
  getMediaBlobUrl: (apiUrl: string) => Promise<ArrayBuffer>;
}

/**
 * Task 7 (2026-09-10): Journal template bridge for /journal side panel.
 *
 * - parseTemplate: POST /api/v1/office/journal/parse-template — parses a
 *   .docx/.doc journal template into a structured JournalSpec.
 * - listSpecs: GET /api/v1/office/journal/specs — all saved specs.
 * - getSpec: GET /api/v1/office/journal/specs/{id} — single spec by id.
 * - validate: POST /api/v1/office/journal/validate — 6-rule validator
 *   (font/size/spacing/margins/headings/citations) against a saved paper.
 * - fillFromContent: POST /api/v1/office/journal/fill-from-content —
 *   structured-fill generator applies spec + content to docx.
 *
 * The bridge mirrors the existing `office` shape (a sibling group
 * returning backend response envelopes). The 5 IPC commands are wired
 * in electron/commands.ts::COMMAND_ROUTES; the renderer-side wrapper
 * lives in src/shared/api/journalApi.ts.
 */
export interface JournalElectronApiBridge {
  parseTemplate: (filePath: string) => Promise<JournalParseTemplateResponse>;
  listSpecs: () => Promise<JournalListSpecsResponse>;
  getSpec: (specId: string) => Promise<JournalGetSpecResponse>;
  validate: (args: { spec_id?: string; file_path?: string }) => Promise<JournalValidateResponse>;
  fillFromContent: (req: JournalFillFromContentRequest) => Promise<JournalFillFromContentResponse>;
}

export interface BackendRequest {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  headers?: HeadersInit;
  body?: unknown;
  /** Optional bounded cancellation timeout for the main-process relay. */
  timeoutMs?: number;
  /** Optional response type for binary data (default: 'json'). */
  responseType?: 'json' | 'arraybuffer' | 'text';
}

export interface ProviderConfigSummary {
  id: string;
  type: 'github' | 'gitee' | 'gitlab' | 'generic-http';
  displayName: string;
  enabled: boolean;
  isDefault: boolean;
  config: Record<string, unknown>;
}

/**
 * Task 10 (2026-09-11): Diagnostic export bridge for LLM trace bundles.
 *
 * - exportBundle: opens a native save dialog and writes a zip archive
 *   containing LLM request/response traces + system metadata. Returns
 *   { ok: true, path } on success or { ok: false, code, error } on failure.
 * - preview: returns a summary of the trace dataset (count, timestamp range,
 *   sample URLs, format version) without triggering export.
 *
 * Backed by `diagnostic:export` and `diagnostic:preview` IPC channels
 * wired in electron/main.ts.
 */
export interface DiagnosticElectronApiBridge {
  exportBundle: (opts: {
    includePrompts: boolean;
    includeHostname: boolean;
  }) => Promise<{ ok: true; path: string } | { ok: false; code: string; error: string }>;
  preview: () => Promise<{
    count: number;
    oldestTs: string | null;
    newestTs: string | null;
    sampleUrls: string[];
    version: string;
  }>;
}

export interface ProvidersElectronApiBridge {
  list: () => Promise<ProviderConfigSummary[]>;
  get: (id: string) => Promise<ProviderConfigSummary | null>;
  add: (
    cfg: Omit<ProviderConfigSummary, 'id'> & { config: Record<string, unknown> },
  ) => Promise<{ id: string }>;
  update: (
    id: string,
    patch: Partial<Omit<ProviderConfigSummary, 'id'>>,
  ) => Promise<{ ok: boolean }>;
  remove: (id: string) => Promise<{ ok: boolean }>;
  setDefault: (id: string) => Promise<{ ok: boolean }>;
  test: (id: string) => Promise<{ ok: boolean; latencyMs: number; error?: string }>;
}

export interface UpdateElectronApiBridge {
  check: () => Promise<CheckResult>;
  download: () => Promise<void>;
  install: () => Promise<void>;
  rollback: (reason?: string) => Promise<void>;
  canRollback: () => Promise<{ allowed: boolean; reason?: string }>;
  setStrategy: (strategy: UpdateStrategy) => Promise<void>;
  getConfig: () => Promise<UpdateConfig>;
  setChannel: (channel: UpdateChannel) => Promise<void>;
  /**
   * 2026-09-19 设置治理: 部分更新更新配置（回滚窗口/检查周期/服务器/遥测/缓存）。
   * 主进程合并后经 ConfigManager 校验落盘，并返回生效后的完整配置。
   */
  setConfigPatch: (patch: Partial<UpdateConfig>) => Promise<UpdateConfig>;
  onStateChanged: (handler: (payload: UpdateStateChangedEvent) => void) => UnlistenFn;
  checkWith: (providerId: string, channel?: string) => Promise<CheckResult | null>;
}

/**
 * 用户反馈系统 IPC 桥 (2026-10-29)。
 *
 * 设计见 docs/technical/109-feedback-relay-deployment.md §11.2。
 * main 侧注册：electron/feedback/feedbackIpc.ts（registerFeedbackIpc）。
 * preload 暴露：electron/preload.ts → window.electronAPI.feedback。
 *
 * - getConfig: 读当前反馈配置（URL + 是否已配密钥 + installationUuid）
 * - setConfig: 更新 URL / 共享密钥（sharedSecret 走 safeStorage 加密）
 *              undefined = 不改动；空串 = 清空
 * - syncNow: 手动触发一次 syncer（返回本轮提交/接收/错误计数）
 * - uploadAttachment: 上传截图等附件（base64 编码，main 侧落 MediaStore）
 */
export interface FeedbackElectronApiBridge {
  getConfig: () => Promise<{
    managerUrl: string;
    hasSecret: boolean;
    installationUuid: string;
    configured: boolean;
    includeDiagnostics: boolean;
  }>;
  setConfig: (patch: {
    managerUrl?: string;
    sharedSecret?: string;
    includeDiagnostics?: boolean;
  }) => Promise<{
    ok: true;
    managerUrl: string;
    hasSecret: boolean;
    installationUuid: string;
    configured: boolean;
    includeDiagnostics: boolean;
  }>;
  syncNow: () => Promise<{ submitted: number; received: number; errors: number }>;
  uploadAttachment: (payload: {
    conversationId: string;
    filename: string;
    mimeType: string;
    dataBase64: string;
  }) => Promise<{ id: string; conversation_id: string }>;
}

/**
 * Phase 3 (2026-09-25): 终端面板 PTY IPC 桥。
 *
 * 管理 Electron 主进程中的 node-pty 子进程。renderer 通过此桥：
 * - create: 启动新 shell（bash/powershell）
 * - write: 发送用户输入（按键/字符串）
 * - resize: 调整终端列/行数（窗口 resize 时联动）
 * - destroy: 终止 PTY 进程
 * - onData / onExit: 订阅 PTY 输出/退出事件
 *
 * 仅桌面端可用；Web 端 `window.electronAPI.pty` 为 undefined。
 */
export interface PtyElectronApiBridge {
  create: (opts?: {
    cols?: number;
    rows?: number;
    cwd?: string;
    shell?: string;
  }) => Promise<{ id: string } | { error: string }>;
  write: (opts: { id: string; data: string }) => Promise<void>;
  resize: (opts: { id: string; cols: number; rows: number }) => Promise<void>;
  destroy: (opts: { id: string }) => Promise<void>;
  onData: (handler: (payload: { id: string; data: string }) => void) => UnlistenFn;
  onExit: (handler: (payload: { id: string; exitCode: number }) => void) => UnlistenFn;
}

/**
 * Phase 4 (2026-09-25): 文件操作桥 — 用系统默认编辑器打开文件。
 * 仅桌面端可用；Web 端 `window.electronAPI.file` 为 undefined。
 */
export interface FileElectronApiBridge {
  /** 用系统默认编辑器打开指定文件（相对工作区路径） */
  openInEditor: (sessionId: string, path: string) => Promise<{ success: true } | { error: string }>;
}

/**
 * Project folder bridge (2026-10-29): open/reveal a registered project
 * directory. The renderer passes only the project id; main resolves the
 * path from the backend.
 */
export interface ProjectElectronApiBridge {
  openFolder: (projectId: string) => Promise<{ success: true } | { error: string }>;
  revealFolder: (projectId: string) => Promise<{ success: true } | { error: string }>;
}

/**
 * Desktop pet bridge. Keep in sync with `electron/pet/types.ts`.
 * Available in both the main window (settings page) and the pet window.
 */
export interface PetConfigBridge {
  version: 1;
  enabled: boolean;
  displayMode: 'desktop' | 'in-app' | 'both' | 'off';
  size: 'mini' | 'small' | 'medium' | 'large' | 'huge';
  tempo: 'quiet' | 'standard' | 'lively';
  reduceMotion: boolean;
  bubbleMode: 'important' | 'always' | 'off';
  soundScenes: { waiting: boolean; error: boolean; done: boolean };
  showSessionTitle: boolean;
  compatibilityMode: 'auto' | 'on' | 'off';
  petPack: string;
  followActiveSession: boolean;
}

export type PetTaskStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface PetTaskReportBridge {
  id: string;
  kind: string;
  title: string;
  status: PetTaskStatus;
  phase?: string | null;
  percent?: number | null;
  sessionId?: string | null;
  runId?: string | null;
  error?: string | null;
  startedAt?: number | null;
  finishedAt?: number | null;
}

export interface PetSessionSummaryBridge {
  sessionId: string;
  sessionTitle: string | null;
  action: string;
  detail: string | null;
  toolName: string | null;
  bubbleKey: string | null;
  todoDone: number;
  todoTotal: number;
  todoActive: string | null;
  progressKind: 'todo' | 'plan' | null;
  contextUsed: number | null;
  contextMax: number | null;
  lastTerminalAction: 'done' | 'error' | null;
  lastTerminalAt: number | null;
  updatedAt: number;
}

export interface PetSnapshotBridge {
  action: string;
  detail: string | null;
  sessionId: string | null;
  sessionTitle: string | null;
  toolName: string | null;
  bubbleKey: string | null;
  bubbleKind: 'info' | 'success' | 'error' | 'waiting' | null;
  todoDone: number;
  todoTotal: number;
  todoActive: string | null;
  progressKind: 'todo' | 'plan' | null;
  contextUsed: number | null;
  contextMax: number | null;
  lastTerminalAction: 'done' | 'error' | null;
  lastTerminalAt: number | null;
  patCount: number;
  bondDays: number;
  activeSessions: number;
  sessions: PetSessionSummaryBridge[];
  tasks: PetTaskReportBridge[];
  updatedAt: number;
}

/**
 * A user-imported pet pack manifest (validated in the main process).
 * Built-in packs are bundled with the renderer and are not returned here.
 */
export interface PetPackManifestBridge {
  id: string;
  name: string;
  version: string;
  license: string;
  source?: string;
  canvas: { width: number; height: number };
  anchor: { x: number; y: number };
  actions: Record<string, string[]>;
}

export interface PetPackImportResultBridge {
  ok: boolean;
  canceled?: boolean;
  error?: string;
  manifest?: PetPackManifestBridge;
  config?: PetConfigBridge;
}

export interface PetPackExportResultBridge {
  ok: boolean;
  canceled?: boolean;
  error?: string;
  path?: string;
}

export interface PetPackDeleteResultBridge {
  ok: boolean;
  error?: string;
}

export interface PetElectronApiBridge {
  getConfig: () => Promise<PetConfigBridge>;
  setConfig: (patch: Partial<PetConfigBridge>) => Promise<PetConfigBridge>;
  getState: () => Promise<PetSnapshotBridge>;
  onState: (handler: (snapshot: PetSnapshotBridge) => void) => UnlistenFn;
  onConfig: (handler: (config: PetConfigBridge) => void) => UnlistenFn;
  ready: () => void;
  openSession: (sessionId: string | null) => void;
  openSettings: () => void;
  showMenu: () => void;
  dragStart: () => void;
  dragMove: () => void;
  dragEnd: () => void;
  resetPosition: () => void;
  setPanel: (open: boolean) => void;
  pat: () => void;
  reportTasks: (tasks: PetTaskReportBridge[]) => void;
  hide: () => void;
  /** Installed user packs (does not include built-in packs). */
  listPacks: () => Promise<PetPackManifestBridge[]>;
  importPack: () => Promise<PetPackImportResultBridge>;
  exportPack: (id: string) => Promise<PetPackExportResultBridge>;
  deletePack: (id: string) => Promise<PetPackDeleteResultBridge>;
}

export interface ElectronAPI {
  /** Authenticated renderer-to-backend request; main injects the local capability. */
  backendRequest<T = unknown>(request: BackendRequest): Promise<T>;
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  /**
   * 开发期右键「检查元素」桥（渲染层自绘菜单按坐标请求 inspect）。
   * 主进程在打包环境（app.isPackaged）下会忽略该请求。
   */
  devtools?: {
    inspectAt: (x: number, y: number) => void;
  };
  /**
   * P8 (2026-09-14): 嵌入模型下载桥 —— models:embedder:download / cancel
   * 原生 IPC；进度经 api.listen('models:embedder:progress') 订阅。
   * payload 缺省时 main 使用内置 EMBEDDER_MODEL_MANIFEST。
   */
  modelDownload?: {
    download: (payload?: {
      baseUrl?: string;
      dirName?: string;
      files?: { name: string; sha256: string }[];
    }) => Promise<{ ok: boolean; totalBytes?: number; error?: string }>;
    cancel: (dirName: string) => Promise<{ ok: boolean }>;
    /** RapidOCR PP-OCRv6 tiny det/rec → userData/models/rapidocr */
    downloadOcr: () => Promise<{ ok: boolean; totalBytes?: number; error?: string }>;
    cancelOcr: () => Promise<{ ok: boolean }>;
    /** 删除受管的 userData/models/rapidocr，恢复包内默认模型 */
    resetOcr: () => Promise<{ ok: boolean; error?: string }>;
  };
  /** P13/P17: sage-file 工作区注册表 —— 渲染端绑定工作区时登记/注销到主进程白名单。 */
  sageFile?: {
    registerRoot: (path: string) => Promise<boolean>;
    unregisterRoot: (path: string) => Promise<boolean>;
    // P22 (2026-09-17): 项目级 allowed_paths 注册 —— 与工作区根 OR-组合。
    registerAllowedPaths: (projectId: string, paths: string[]) => Promise<void>;
    unregisterAllowedPaths: (projectId: string) => Promise<boolean>;
  };
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
  /** Workspace MCP Server (M4) — optional: absent in web / older preloads. */
  remoteMcp?: RemoteMcpElectronApiBridge;
  arenaToken: ArenaTokenElectronApiBridge;
  office: OfficeElectronApiBridge;
  project: ProjectElectronApiBridge;
  /** Desktop pet window + settings bridge (2026-10-30). */
  pet?: PetElectronApiBridge;
  media: MediaElectronApiBridge;
  journal: JournalElectronApiBridge;
  updates: UpdateElectronApiBridge;
  providers: ProvidersElectronApiBridge;
  /**
   * 用户反馈系统 (2026-10-29):管理员转发 URL + 共享密钥 + 双向会话。
   * 仅桌面端可用；Web 端 `window.electronAPI.feedback` 为 undefined。
   */
  feedback?: FeedbackElectronApiBridge;
  /**
   * Task 10 (2026-09-11): Diagnostic export bridge for LLM trace bundles.
   * Two methods — exportBundle (native save dialog → zip) and preview
   * (summary stats without export). IPC channels: diagnostic:export,
   * diagnostic:preview.
   */
  diagnostic?: DiagnosticElectronApiBridge;
  /**
   * Memory IPC bridge (Gap B + Gap D). Surfaced via `electron/preload.ts`
   * which delegates to `sage:invoke` IPC commands defined in
   * `electron/commands.ts`. Backend wiring lives in
   * `backend/memory/lifecycle.py` (auto_memory gate) and the existing
   * `/api/v1/memory/*` endpoints (T1 wired the IPC routes).
   */
  memory: MemoryElectronApiBridge;
  /** P2 应用内浏览器面板（BrowserView，共享登录分区）。 */
  browserPanel?: BrowserPanelElectronApiBridge;
  /**
   * Phase 6 (2026-06-27): Native folder picker (used by LLM Wiki and Office).
   * Returns absolute path string, or null if user cancelled.
   */
  selectDirectory: (opts: {
    intent: 'create' | 'open';
    defaultPath?: string;
  }) => Promise<string | null>;
  /** 打开原生单文件选择器（Wiki 来源导入）；取消返回 null。 */
  selectFile?: (opts?: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<string | null>;
  /** live-events P1 附带: 审批等待 OS 通知（点击聚焦窗口; 不支持平台降级）。 */
  notifyApproval?: (payload: { title?: string; body?: string }) => Promise<{
    ok: boolean;
    reason?: string;
  }>;
  /** S8 (round4): 分会话 OS 通知。main 展示原生 Notification,点击回发 session-notify-click。 */
  notifySession?: (payload: {
    sessionId: string;
    title: string;
    body: string;
  }) => Promise<{ shown: boolean }>;
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
  /**
   * 2026-09-15: 读取当前生效的 SAGE_LOG_LEVEL。渲染端组件挂载时拉取一次,
   * 避免在 Diagnostics 卡片切到其他级别 → 切走页面 → 切回来时被硬编码的
   * 默认值 'info' 覆盖。无值/无效值返回 DEFAULT_LOG_LEVEL ('info')。
   */
  getLogLevel?: () => Promise<LogLevel>;
  /**
   * 2026-08-27: 演示模式开关持久化. 用户在 Settings → 通用 切换后,
   * 写入 <userData>/sage-demo-mode.json, 下次启动 main 进程读取生效.
   */
  resetDemoMode?: () => Promise<{ ok: boolean; error?: string }>;
  setDemoMode?: (demoMode: boolean) => Promise<{ ok: boolean; error?: string }>;
  /**
   * P2-3.11 (2026-09-13): Artifacts 独立窗口。
   * 双击 Artifact → 弹出独立 BrowserWindow 展示 HTML 内容。
   * 仅支持 kind === 'html';其他类型返回 {ok:false, reason:'unsupported'}。
   */
  openArtifactWindow: (artifact: {
    id: string;
    name: string;
    kind: string;
    path: string;
  }) => Promise<{ ok: boolean; reason?: string }>;
  /** E-2 (round5 批次 E): 关闭即隐藏到托盘偏好读写 */
  getCloseToTray?: () => Promise<{ enabled: boolean }>;
  setCloseToTray?: (enabled: boolean) => Promise<{ ok: boolean; enabled: boolean }>;
  /** 日志时区 (2026-09-17): 读写日志时间戳时区设置 */
  getLogTimezone?: () => Promise<{ logTimezone: string }>;
  setLogTimezone?: (logTimezone: string) => Promise<{ ok: boolean; error?: string }>;
  /**
   * 2026-08-27: 演示模式同步标志. main 进程激活演示模式时经
   * webPreferences.additionalArguments → preload argv 注入, 首屏请求在
   * settings 加载完成前即可命中拦截。
   */
  demoMode?: boolean;
  /** 更新日志 API — 读取 CHANGELOG.md */
  changelogAPI?: {
    read: () => Promise<string>;
  };
  /** 帮助文档 API — 读取 user-manual markdown */
  helpAPI?: {
    readUserManual: (filename: string) => Promise<string>;
  };
  /**
   * Phase 3 (2026-09-25): 终端面板 PTY 桥。
   * 在 Electron 主进程管理 node-pty 子进程，renderer 通过此桥发送输入/接收输出。
   * 仅桌面端可用；Web 端 electronAPI 缺失时组件应降级显示"仅桌面端可用"。
   */
  pty?: PtyElectronApiBridge;
  /**
   * Phase 4 (2026-09-25): 文件操作桥 — 用系统默认编辑器打开变更文件。
   * 仅桌面端可用；Web 端 electronAPI 缺失时组件应降级显示提示。
   */
  file?: FileElectronApiBridge;
  /**
   * P2 (2026-10-19): detected project root from startup cwd.
   * Returns the path if a project marker was found within 5 levels, else null.
   */
  getDetectedProjectRoot?: () => Promise<string | null>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
