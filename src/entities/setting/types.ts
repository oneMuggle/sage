/** Settings version for future migration support */
export const SETTINGS_VERSION = '4.0.0';

/** localStorage key for settings persistence */
export const SETTINGS_STORAGE_KEY = 'sage-settings';

/** Model capability types */
export type ModelCapability = 'chat' | 'vision' | 'embedding';

/** A model discovered from an endpoint's /v1/models */
export interface DiscoveredModel {
  id: string;
  capabilities: ModelCapability[];
  endpointId: string;
}

/**
 * 端点协议 — Task 1 (2026-08-23): 用于区分 LM Studio / Ollama / OpenAI 兼容 / Anthropic / Gemini.
 *
 * - 'openai-compatible': 默认值, 适用于 OpenAI / LM Studio / 一切 ``/v1/*`` 接口.
 * - 'ollama': Ollama 原生 ``/api/chat`` 接口 (非 ``/v1/chat/completions``).
 * - 'anthropic': Anthropic Messages API 协议 (v1/chat/completions 的反义词).
 * - 'gemini': Google Gemini generateContent 接口.
 *
 * 后端 _migrate_default_protocol 对历史端点写入默认值 'openai-compatible',
 * 前端新建端点也强制写入, 防止空字符串落到 DB.
 */
export type EndpointProtocol = 'openai-compatible' | 'anthropic' | 'gemini' | 'ollama';

/** Configuration for a single endpoint */
export interface EndpointConfig {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  /**
   * 端点协议 (Task 1 2026-08-23): 'openai-compatible' (默认) | 'anthropic' | 'gemini' | 'ollama'.
   * 历史端点 (没有此字段) 经后端 ``_migrate_default_protocol`` fallback 到 'openai-compatible'.
   */
  protocol: EndpointProtocol;
  /**
   * 上游模型 ID — LM Studio 用户常填的 ``qwen2.5-7b-instruct`` / ``llama-3-8b-instruct`` 等.
   * 与 localModelPath 互斥但并存以支持 hybrid (Ollama 边远端边本地).
   */
  modelId: string;
  /**
   * 本地模型文件绝对路径 — Ollama 等本地推理后端用.
   * 与 modelId 互斥但并存以支持 hybrid; 留空表示走远端 modelId.
   */
  localModelPath: string;
  discoveredModels: DiscoveredModel[];
  lastDiscoveredAt: number | null;
  /**
   * 2026-08-26 (OWASP A02:2021): 后端 redact_secrets 在 GET 响应里把
   * apiKey 置为 "" 并打这个 flag. 客户端按 id 在 localStorage 中找回真实 key.
   * sanitizeForBackend 不在白名单里, 不会回写; 仅在 GET → loadSettings 路径消费.
   */
  hasApiKey?: boolean;
}

/** User's model selection — binds a model to its source endpoint */
export interface ModelSelection {
  endpointId: string | null;
  modelId: string | null;
}

/** User's model selections per type */
export interface ModelSelections {
  chatModel: ModelSelection;
  visionModel: ModelSelection;
  embeddingModel: ModelSelection;
}

/** Wiki feature flags */
export interface WikiSettings {
  /** When true, project create/open shows a native folder picker "Browse" button. Set false to fall back to plain text input. */
  useFolderPicker: boolean;
}

// Wave 3 P2-9 (2026-08-14): 编排执行参数（前端 UI 渲染 5 个数值；scratchRoot
// 仅后端配置，不在此 interface —— 见 storage 层注释）。
export interface OrchSettings {
  maxConcurrentSubagents: number; // 4
  maxAggregateChars: number; // 120 * 1024
  maxSubagentResultChars: number; // 50 * 1024
  maxRetries: number; // 2
  maxLaneIterations: number; // 8
  // 子代理（agent tool）单次委派的 ReAct 迭代预算。默认 6 与后端
  // ``OrchSettings.max_subagent_iterations`` 默认对齐；用户可在此调整。
  maxSubagentIterations: number; // 6
  worktreeIsolation: boolean; // false
}

/** All application settings */
export interface AppSettings {
  // General
  streaming: boolean;
  autoMemory: boolean;
  confirmDelete: boolean;

  // Memory — separate field from autoMemory (which is "auto-extract in
  // conversation"). memoryServerSync is the planned "sync to internal
  // server" feature; UI exposes it but the backend endpoint is not yet
  // wired up — see docs/plans/2026-08-09_feature-optimization-proposal.md
  // §1.4 for the cleanup decision.
  memoryServerSync: boolean;

  // Endpoint & Model
  endpoints: EndpointConfig[];
  modelSelections: ModelSelections;
  maxContext: number;
  temperature: number;

  // Task 1 (2026-08-23): IANA 时区 — 用户报告时区与本地不一致时排查用.
  // 默认 'Asia/Shanghai' (与后端 settings_canonicalizer.DEFAULT_TIMEZONE 对齐).
  // 后端 zoneinfo 校验, 非法值 → 422.
  timezone: string;

  // Wiki
  wiki: WikiSettings;

  // Wave 3 P2-9
  orch: OrchSettings;

  // 演示模式开关 (2026-08-27): 启用后 Electron main 进程跳过 Python 后端
  // spawn, 前端可走 /demo 路由录屏. 关闭时回到正常 LLM 调用路径.
  demoMode: boolean;

  // Internal
  version: string;
}

export const DEFAULT_ENDPOINT: EndpointConfig = {
  id: '',
  name: '',
  baseUrl: '',
  apiKey: '',
  // Task 1 (2026-08-23): 协议默认 'openai-compatible', 与后端 _migrate_default_protocol 对齐.
  protocol: 'openai-compatible',
  modelId: '',
  localModelPath: '',
  discoveredModels: [],
  lastDiscoveredAt: null,
};

const DEFAULT_MODEL_SELECTION: ModelSelection = {
  endpointId: null,
  modelId: null,
};

const DEFAULT_MODEL_SELECTIONS: ModelSelections = {
  chatModel: { ...DEFAULT_MODEL_SELECTION },
  visionModel: { ...DEFAULT_MODEL_SELECTION },
  embeddingModel: { ...DEFAULT_MODEL_SELECTION },
};

/** Sensible defaults for all settings */
export const DEFAULT_ORCH_SETTINGS: OrchSettings = {
  maxConcurrentSubagents: 4,
  maxAggregateChars: 120 * 1024,
  maxSubagentResultChars: 50 * 1024,
  maxRetries: 2,
  maxLaneIterations: 8,
  maxSubagentIterations: 6,
  worktreeIsolation: false,
};

/** Sensible defaults for all settings */
export const DEFAULT_SETTINGS: AppSettings = {
  // General
  streaming: true,
  autoMemory: true,
  confirmDelete: true,

  // Memory
  memoryServerSync: false,

  // Endpoint & Model
  endpoints: [],
  modelSelections: DEFAULT_MODEL_SELECTIONS,
  maxContext: 4096,
  temperature: 0.7,

  // Task 1 (2026-08-23): 时区默认 'Asia/Shanghai' — 与后端 canonicalizer
  // DEFAULT_TIMEZONE 对齐. 后端 zoneinfo 校验; 前端只 export 默认值, 由
  // mergeWithDefaults 兜底补值.
  timezone: 'Asia/Shanghai',

  // Wiki
  wiki: {
    useFolderPicker: true,
  },

  // Wave 3 P2-9
  orch: DEFAULT_ORCH_SETTINGS,

  // 演示模式: 默认关闭. 开启后 main 进程跳过 Python 后端启动.
  demoMode: false,

  // Internal
  version: SETTINGS_VERSION,
};

/**
 * Resolve the endpoint that backs a given model selection.
 * Returns undefined when the selection is empty or the endpoint was deleted.
 */
export function resolveEndpoint(
  selection: ModelSelection,
  endpoints: EndpointConfig[],
): EndpointConfig | undefined {
  if (!selection.endpointId) return undefined;
  return endpoints.find((ep) => ep.id === selection.endpointId);
}

/**
 * 演示模式 (2026-08-27): 演示用端点 + 模型选择注入.
 *
 * settingsStore.loadSettings 在演示标志激活 (window.electronAPI.demoMode,
 * main 进程经 argv 注入) 时调用本函数. 演示模式下 Python 后端不启动,
 * 也没有真实 LLM 端点, 但聊天页发送前置校验要求
 * ``resolveEndpoint(chatModel).baseUrl`` 与 ``chatModel.modelId`` 非空,
 * 否则录屏时对话流发不出去. 这里往内存 settings 注入一份仿真本地端点
 * (仅 settingsStore set, 不回写 localStorage), 关闭演示模式即恢复真实配置.
 *
 * 规则:
 * - 用户已配置端点 → 不覆盖
 * - 对应模型选择已有 modelId → 不覆盖
 * - 强制 demoMode: true (设置页开关显示与运行态一致)
 */
export const DEMO_ENDPOINT_ID = 'ep-demo-lmstudio';

export const DEMO_ENDPOINT_MODELS: DiscoveredModel[] = [
  {
    id: 'qwen2.5-14b-instruct',
    capabilities: ['chat', 'vision'],
    endpointId: DEMO_ENDPOINT_ID,
  },
  { id: 'bge-m3', capabilities: ['embedding'], endpointId: DEMO_ENDPOINT_ID },
];

function createDemoEndpoint(): EndpointConfig {
  return {
    id: DEMO_ENDPOINT_ID,
    name: 'LM Studio (本地)',
    baseUrl: 'http://127.0.0.1:1234/v1',
    apiKey: '',
    protocol: 'openai-compatible',
    modelId: 'qwen2.5-14b-instruct',
    localModelPath: '',
    discoveredModels: [...DEMO_ENDPOINT_MODELS],
    lastDiscoveredAt: Date.now() - 2 * 60 * 60 * 1000,
  };
}

function hasUsableEndpoint(endpoint: EndpointConfig | undefined): endpoint is EndpointConfig {
  return Boolean(endpoint?.id && endpoint.baseUrl);
}

function fillSelection(
  sel: ModelSelection,
  endpoints: EndpointConfig[],
  fallbackModelId: string,
): { selection: ModelSelection; endpoints: EndpointConfig[] } {
  const selectedEndpoint = endpoints.find((endpoint) => endpoint.id === sel.endpointId);
  if (sel.modelId && hasUsableEndpoint(selectedEndpoint)) {
    return { selection: sel, endpoints };
  }

  const matchingEndpoint = endpoints.find(
    (endpoint) =>
      hasUsableEndpoint(endpoint) &&
      endpoint.discoveredModels.some((model) => model.id === fallbackModelId),
  );
  if (matchingEndpoint) {
    return {
      selection: { endpointId: matchingEndpoint.id, modelId: fallbackModelId },
      endpoints,
    };
  }

  const demoEndpoint =
    endpoints.find((endpoint) => endpoint.id === DEMO_ENDPOINT_ID) ?? createDemoEndpoint();
  return {
    selection: { endpointId: demoEndpoint.id, modelId: fallbackModelId },
    endpoints: endpoints.some((endpoint) => endpoint.id === DEMO_ENDPOINT_ID)
      ? endpoints
      : [...endpoints, demoEndpoint],
  };
}

export function withDemoSettingsDefaults(s: AppSettings): AppSettings {
  const chat = fillSelection(s.modelSelections.chatModel, s.endpoints, 'qwen2.5-14b-instruct');
  const vision = fillSelection(
    s.modelSelections.visionModel,
    chat.endpoints,
    'qwen2.5-14b-instruct',
  );
  const embedding = fillSelection(s.modelSelections.embeddingModel, vision.endpoints, 'bge-m3');
  return {
    ...s,
    demoMode: true,
    endpoints: embedding.endpoints,
    modelSelections: {
      chatModel: chat.selection,
      visionModel: vision.selection,
      embeddingModel: embedding.selection,
    },
  };
}
