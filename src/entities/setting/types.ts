/** Settings version for future migration support */
export const SETTINGS_VERSION = '4.0.0';

/** localStorage key for settings persistence */
export const SETTINGS_STORAGE_KEY = 'sage-settings';

/** Model capability types */
export type ModelCapability = 'chat' | 'vision' | 'embedding' | 'tts' | 'asr' | 'image_gen';

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
  ttsModel: ModelSelection;
  asrModel: ModelSelection;
  imageGenModel: ModelSelection;
}

/** Wiki feature flags */
export interface WikiSettings {
  /** When true, project create/open shows a native folder picker "Browse" button. Set false to fall back to plain text input. */
  useFolderPicker: boolean;
}

// Wave 3 P2-9 (2026-08-14): 编排执行参数。RD16 (round26) 起前端键集与
// 后端 OrchSettings 完全对齐（scratchRoot 此前仅后端配置，现透出设置页）。
export interface OrchSettings {
  maxConcurrentSubagents: number; // 4
  maxAggregateChars: number; // 120 * 1024
  maxSubagentResultChars: number; // 50 * 1024
  maxRetries: number; // 2
  maxLaneIterations: number; // 12 (alpha.36: 8 → 12, 减少"复杂度超上限"误报)
  // 子代理（agent tool）单次委派的 ReAct 迭代预算。默认 10 与后端
  // ``OrchSettings.max_subagent_iterations`` 默认对齐；用户可在此调整。
  maxSubagentIterations: number; // 10 (alpha.36: 6 → 10, 减少"复杂度超上限"误报)
  maxPrimaryIterations: number; // 15 (与 profiles.py primary 对齐)
  maxCoderIterations: number; // 15 (与 profiles.py coder 对齐)
  maxReviewerIterations: number; // 8 (与 profiles.py reviewer 对齐)
  maxWriterIterations: number; // 5 (与 profiles.py writer 对齐)
  worktreeIsolation: boolean; // false
  // RD16 (round26): scratch 根目录名（相对 data 目录），dispatcher 与
  // orchestration_router 的子任务 scratch 目录均落在其下。
  scratchRoot: string; // 'orch_scratch'
  // live-events P1 (2026-09-06): 新 run 子代理审批模式默认值。
  // "ask" = 风险工具逐次审批（子代理审批请求转发前端弹窗）;
  // "auto" = 非危险工具自动批准（破坏性/可疑命令/工作区越界仍转人工）。
  // 与后端 ``OrchSettings.subagent_approval_mode`` camelCase 对齐。
  subagentApprovalMode: 'ask' | 'auto';
  // BU4 (round11/14): run 级 token 预算（该 run 首次派发起，本 session 累计
  // total_tokens 上限）。0 = 关闭。超限后剩余任务收口、后续派发被拒。
  runTokenBudget: number; // 0
  // BU11 (round21): run 级墙钟上限（分钟）。0 = 关闭。与 token 预算互补——
  // 管住"每个任务都正常但整体跑飞"的失控形态。
  runWallClockLimitMinutes: number; // 0
  // O2 (round8): 单个子任务 wall-clock 超时（秒）。0 = 关闭。超时任务强制
  // 终止置 failed（error 前缀 task_timeout:），下游依赖级联收口。
  subagentTaskTimeoutS: number; // 900
  // RD14 (round22): retry_of 重派链上限——同一任务被连续重派超过 N 次后
  // 拒绝再次重派，防失败计划 rerun 无限循环。
  maxRetryOfChains: number; // 10
  // Round 1 (2026-09-19) 计划前置: multi 拆解前的澄清+侦察总开关（默认开）。
  // 与后端 OrchSettings.plan_preflight_enabled camelCase 对齐。
  planPreflightEnabled: boolean; // true
  // Round 1: 侦察先行单独开关（澄清不受它控制；总闸关闭时两者皆停）。
  planScoutEnabled: boolean; // true
}

/** All application settings */
export interface AppSettings {
  // General
  streaming: boolean;
  autoMemory: boolean;
  confirmDelete: boolean;

  // Endpoint & Model
  endpoints: EndpointConfig[];
  modelSelections: ModelSelections;
  maxContext: number;
  // Task 5 (2026-09-15): auto context window from catalog resolution.
  // false = use maxContext as manual fixed value; true = resolve from catalog.
  autoContext: boolean;
  temperature: number;

  // Task 1 (2026-08-23): IANA 时区 — 用户报告时区与本地不一致时排查用.
  // 默认 = 系统探测时区 (见 detectSystemTimezone), 后端 zoneinfo 校验,
  // 非法值 → 422.
  timezone: string;

  // 日志时区 (2026-09-17): 控制日志时间戳使用的时区.
  // 'UTC' = 使用 UTC 时间 (默认, 历史行为)
  // 'local' = 使用系统本地时区
  // IANA 时区字符串 = 使用指定时区 (如 'Asia/Shanghai')
  logTimezone: string;

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
  ttsModel: { ...DEFAULT_MODEL_SELECTION },
  asrModel: { ...DEFAULT_MODEL_SELECTION },
  imageGenModel: { ...DEFAULT_MODEL_SELECTION },
};

/** Sensible defaults for all settings */
export const DEFAULT_ORCH_SETTINGS: OrchSettings = {
  maxConcurrentSubagents: 4,
  maxAggregateChars: 120 * 1024,
  maxSubagentResultChars: 50 * 1024,
  maxRetries: 2,
  maxLaneIterations: 12,
  maxSubagentIterations: 10,
  maxPrimaryIterations: 15,
  maxCoderIterations: 15,
  maxReviewerIterations: 8,
  maxWriterIterations: 5,
  worktreeIsolation: false,
  scratchRoot: 'orch_scratch',
  subagentApprovalMode: 'ask',
  runTokenBudget: 0,
  runWallClockLimitMinutes: 0,
  subagentTaskTimeoutS: 900,
  maxRetryOfChains: 10,
  planPreflightEnabled: true,
  planScoutEnabled: true,
};

/** 系统 IANA 时区探测；不可用 / 返回空时回退 'Asia/Shanghai'（历史默认）。 */
export function detectSystemTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
  } catch {
    return 'Asia/Shanghai';
  }
}

/** Sensible defaults for all settings */
export const DEFAULT_SETTINGS: AppSettings = {
  // General
  streaming: true,
  autoMemory: true,
  confirmDelete: true,

  // Endpoint & Model
  endpoints: [],
  modelSelections: DEFAULT_MODEL_SELECTIONS,
  maxContext: 4096,
  // 默认走 catalog 自动解析上下文窗口（后端 modelWindows 默认口径一致）;
  // 只有 autoContext=false 时 maxContext 才作为固定上限生效。
  autoContext: true,
  temperature: 0.7,

  // Task 1 (2026-08-23): 时区默认 = 系统 IANA 时区（浏览器探测）, 探测失败
  // 回退 'Asia/Shanghai' — 后端 canonicalizer 的 DEFAULT_TIMEZONE 仅作后端
  // 侧兜底, 前端优先给真实本地值。后端 zoneinfo 校验; 非法值 → 422.
  timezone: detectSystemTimezone(),

  // 日志时区默认 'UTC' — 保持历史行为. 用户可在设置页切换为 'local' 或 IANA 时区.
  logTimezone: 'UTC',

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
      (endpoint.discoveredModels ?? []).some((model) => model.id === fallbackModelId),
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
      ttsModel: s.modelSelections.ttsModel,
      asrModel: s.modelSelections.asrModel,
      imageGenModel: s.modelSelections.imageGenModel,
    },
  };
}
