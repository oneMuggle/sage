import type { SettingsTabKey } from './settingsSearchIndex';

const visibleTabs: readonly SettingsTabKey[] = [
  'basic',
  'memory-knowledge',
  'tools-connections',
  'endpoints',
  'models',
  'orchestration',
  'memory',
  'network',
  'mcp',
  'zotero',
  'runtime',
  'evolution',
  'updates',
  'usage-stats',
  'providers',
];

/** Keep old settings bookmarks, never render an unknown/hidden initial tab. */
export function initialSettingsTab(value: string | null, providersEnabled = false): SettingsTabKey {
  if (value === 'general') return 'basic';
  if (value === 'providers' && !providersEnabled) return 'basic';
  return visibleTabs.includes(value as SettingsTabKey) ? (value as SettingsTabKey) : 'basic';
}
