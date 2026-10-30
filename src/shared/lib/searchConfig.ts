/** Network search preferences helpers (preference key: `search_config`). */

export interface SearchConfigPayload {
  order: string[];
  tavily_key: string;
  zhipu_key: string;
}

/**
 * Read the Tavily API key out of the persisted `search_config` preference.
 * Malformed / missing values degrade to an empty string so the caller can
 * disable research instead of crashing the settings panel.
 */
export function parseTavilyKey(raw: string | null): string {
  if (!raw) return '';
  try {
    const parsed = JSON.parse(raw) as { tavily_key?: unknown };
    return typeof parsed.tavily_key === 'string' ? parsed.tavily_key.trim() : '';
  } catch {
    return '';
  }
}
