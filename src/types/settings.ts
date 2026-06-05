/** Settings version for future migration support */
export const SETTINGS_VERSION = '2.0.0';

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
  isActive: boolean;
  discoveredModels: DiscoveredModel[];
  lastDiscoveredAt: number | null;
}

/** User's model selections per type */
export interface ModelSelections {
  chatModelId: string | null;
  visionModelId: string | null;
  embeddingModelId: string | null;
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

  // Internal
  version: string;
}

export const DEFAULT_ENDPOINT: EndpointConfig = {
  id: '',
  name: '',
  baseUrl: '',
  apiKey: '',
  isActive: false,
  discoveredModels: [],
  lastDiscoveredAt: null,
};

const DEFAULT_MODEL_SELECTIONS: ModelSelections = {
  chatModelId: null,
  visionModelId: null,
  embeddingModelId: null,
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

  // Internal
  version: SETTINGS_VERSION,
};
