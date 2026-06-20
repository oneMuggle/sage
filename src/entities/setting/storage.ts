import {
  AppSettings,
  DEFAULT_ENDPOINT,
  DEFAULT_SETTINGS,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from './types';
import type { EndpointConfig, ModelSelection } from './types';

/**
 * Load settings from localStorage, merge with defaults.
 * Handles v1 → v3 and v2 → v3 migration if needed.
 */
export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };

    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const version = parsed.version as string | undefined;

    if (!version || version === '1.0.0') {
      return migrateFromV1(parsed);
    }

    if (version === '2.0.0') {
      return migrateFromV2(parsed);
    }

    return mergeWithDefaults(parsed as Partial<AppSettings>);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

/**
 * Migrate v1 settings (apiUrl + model) to v3 (endpoints + ModelSelection bindings).
 */
function migrateFromV1(parsed: Record<string, unknown>): AppSettings {
  const v1ApiUrl = (parsed.apiUrl as string) ?? '';
  const v1Model = (parsed.model as string) ?? '';

  const endpointId = v1ApiUrl ? crypto.randomUUID() : '';

  const endpoint: EndpointConfig = v1ApiUrl
    ? {
        ...DEFAULT_ENDPOINT,
        id: endpointId,
        name: '默认端点',
        baseUrl: v1ApiUrl,
        apiKey: '',
        discoveredModels: v1Model ? [{ id: v1Model, capabilities: ['chat'], endpointId }] : [],
        lastDiscoveredAt: null,
      }
    : { ...DEFAULT_ENDPOINT };

  const chatModel: ModelSelection = v1Model
    ? { endpointId: endpointId || null, modelId: v1Model }
    : { endpointId: null, modelId: null };

  return {
    ...DEFAULT_SETTINGS,
    endpoints: endpoint.baseUrl ? [endpoint] : [],
    modelSelections: {
      chatModel,
      visionModel: { endpointId: null, modelId: null },
      embeddingModel: { endpointId: null, modelId: null },
    },
    version: SETTINGS_VERSION,
  };
}

/**
 * Migrate v2 settings (isActive + flat modelSelections) to v3
 * (endpoint-bound ModelSelection objects, no isActive).
 */
function migrateFromV2(parsed: Record<string, unknown>): AppSettings {
  // Extract old-format fields
  const oldEndpoints = (parsed.endpoints as Array<Record<string, unknown>>) ?? [];
  const oldSelections = (parsed.modelSelections as Record<string, unknown>) ?? {};

  // Find the previously-active endpoint ID
  const activeEp = oldEndpoints.find((ep) => ep.isActive === true);
  const activeEndpointId = (activeEp?.id as string) ?? null;

  // Strip isActive from all endpoints
  const endpoints: EndpointConfig[] = oldEndpoints.map((ep) => ({
    id: ep.id as string,
    name: (ep.name as string) ?? '',
    baseUrl: (ep.baseUrl as string) ?? '',
    apiKey: (ep.apiKey as string) ?? '',
    discoveredModels: (ep.discoveredModels as EndpointConfig['discoveredModels']) ?? [],
    lastDiscoveredAt: (ep.lastDiscoveredAt as number | null) ?? null,
  }));

  // Convert flat model IDs to bound ModelSelection objects
  const toModelSelection = (modelId: unknown): ModelSelection => {
    const id = (modelId as string) ?? null;
    return id ? { endpointId: activeEndpointId, modelId: id } : { endpointId: null, modelId: null };
  };

  return {
    ...DEFAULT_SETTINGS,
    ...(parsed as Partial<AppSettings>),
    endpoints,
    modelSelections: {
      chatModel: toModelSelection(oldSelections.chatModelId),
      visionModel: toModelSelection(oldSelections.visionModelId),
      embeddingModel: toModelSelection(oldSelections.embeddingModelId),
    },
    version: SETTINGS_VERSION,
  };
}

/**
 * Save a partial settings update. Merges with current settings.
 */
export function saveSettings(partial: Partial<AppSettings>): void {
  try {
    const current = loadSettings();
    const merged: AppSettings = {
      ...current,
      ...partial,
      endpoints: partial.endpoints ?? current.endpoints,
      modelSelections: partial.modelSelections ?? current.modelSelections,
      version: SETTINGS_VERSION,
    };
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // Silently fail — settings are non-critical
  }
}

/**
 * Reset all settings to their default values.
 */
export function resetSettings(): void {
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(DEFAULT_SETTINGS));
  } catch {
    // Silently fail
  }
}

/**
 * Merge a partial settings object with defaults.
 */
function mergeWithDefaults(partial: Partial<AppSettings>): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    endpoints: partial.endpoints ?? DEFAULT_SETTINGS.endpoints,
    modelSelections: partial.modelSelections ?? DEFAULT_SETTINGS.modelSelections,
    version: partial.version ?? SETTINGS_VERSION,
  };
}
