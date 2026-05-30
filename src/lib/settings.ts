import {
  AppSettings,
  DEFAULT_SETTINGS,
  DEFAULT_ENDPOINT,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from '../types/settings'
import type { EndpointConfig } from '../types/settings'

/**
 * Load settings from localStorage, merge with defaults.
 * Handles v1 → v2 migration if needed.
 */
export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }

    const parsed = JSON.parse(raw) as Record<string, unknown>
    const version = parsed.version as string | undefined

    if (!version || version === '1.0.0') {
      return migrateFromV1(parsed)
    }

    return mergeWithDefaults(parsed as Partial<AppSettings>)
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

/**
 * Migrate v1 settings (apiUrl + model) to v2 (endpoints + modelSelections).
 */
function migrateFromV1(parsed: Record<string, unknown>): AppSettings {
  const v1ApiUrl = (parsed.apiUrl as string) ?? ''
  const v1Model = (parsed.model as string) ?? ''

  const endpoint: EndpointConfig = v1ApiUrl
    ? {
        ...DEFAULT_ENDPOINT,
        id: crypto.randomUUID(),
        name: '默认端点',
        baseUrl: v1ApiUrl,
        apiKey: '',
        isActive: true,
        discoveredModels: v1Model
          ? [{ id: v1Model, capabilities: ['chat'], endpointId: '' }]
          : [],
        lastDiscoveredAt: null,
      }
    : { ...DEFAULT_ENDPOINT }

  return {
    ...DEFAULT_SETTINGS,
    endpoints: endpoint.baseUrl ? [endpoint] : [],
    modelSelections: {
      chatModelId: v1Model || null,
      visionModelId: null,
      embeddingModelId: null,
    },
    version: SETTINGS_VERSION,
  }
}

/**
 * Save a partial settings update. Merges with current settings.
 */
export function saveSettings(partial: Partial<AppSettings>): void {
  try {
    const current = loadSettings()
    const merged: AppSettings = {
      ...current,
      ...partial,
      endpoints: partial.endpoints ?? current.endpoints,
      modelSelections: partial.modelSelections ?? current.modelSelections,
      version: SETTINGS_VERSION,
    }
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(merged))
  } catch {
    // Silently fail — settings are non-critical
  }
}

/**
 * Reset all settings to their default values.
 */
export function resetSettings(): void {
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(DEFAULT_SETTINGS))
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
  }
}
