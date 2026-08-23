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

/** Configuration for a single OpenAI-compatible endpoint */
export interface EndpointConfig {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  discoveredModels: DiscoveredModel[];
  lastDiscoveredAt: number | null;
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

  // Wiki
  wiki: WikiSettings;

  // Wave 3 P2-9
  orch: OrchSettings;

  // Internal
  version: string;
}

export const DEFAULT_ENDPOINT: EndpointConfig = {
  id: '',
  name: '',
  baseUrl: '',
  apiKey: '',
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

  // Wiki
  wiki: {
    useFolderPicker: true,
  },

  // Wave 3 P2-9
  orch: DEFAULT_ORCH_SETTINGS,

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
