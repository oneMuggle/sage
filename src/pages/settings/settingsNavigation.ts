import type { SettingsTabKey } from './settingsSearchIndex';

const visibleTabs: readonly SettingsTabKey[] = [
  'basic',
  'tools-connections',
  'endpoints',
  'models',
  'orchestration',
  'memory',
  'network',
  'mcp',
  'remote-workspaces',
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
  // 上游把「记忆与知识」tab 重命名为 memory；旧书签按别名迁回，不落到 basic。
  if (value === 'memory-knowledge') return 'memory';
  if (value === 'providers' && !providersEnabled) return 'basic';
  return visibleTabs.includes(value as SettingsTabKey) ? (value as SettingsTabKey) : 'basic';
}
