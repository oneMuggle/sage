/** Settings version for future migration support */
export const SETTINGS_VERSION = '3.0.0';

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

/** All application settings */
export interface AppSettings {
  // General
  streaming: boolean;
  autoMemory: boolean;
  confirmDelete: boolean;
  compactMode: boolean;

  // Endpoint & Model
  endpoints: EndpointConfig[];
  modelSelections: ModelSelections;
  maxContext: number;
  temperature: number;

  // Network
  proxyMode: 'system' | 'custom' | 'direct';
  proxyUrl: string;
  tlsVersion: '1.2' | '1.3';

  // Wiki
  wiki: WikiSettings;

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
export const DEFAULT_SETTINGS: AppSettings = {
  // General
  streaming: true,
  autoMemory: true,
  confirmDelete: true,
  compactMode: false,

  // Endpoint & Model
  endpoints: [],
  modelSelections: DEFAULT_MODEL_SELECTIONS,
  maxContext: 4096,
  temperature: 0.7,

  // Network
  proxyMode: 'system',
  proxyUrl: 'http://proxy.internal:3128',
  tlsVersion: '1.2',

  // Wiki
  wiki: {
    useFolderPicker: true,
  },

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
