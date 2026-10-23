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
  'plugins',
  'remote-workspaces',
  'zotero',
  'runtime',
  'evolution',
  'harness',
  'updates',
  'usage-stats',
  'providers',
  // T-3/T-4: 技能设置 Tab（脚本执行开关 + 技能目录）
  'skills',
];

/** Keep old settings bookmarks, never render an unknown/hidden initial tab. */
export function initialSettingsTab(value: string | null, providersEnabled = false): SettingsTabKey {
  if (value === 'general') return 'basic';
  // 上游把「记忆与知识」tab 重命名为 memory；旧书签按别名迁回，不落到 basic。
  if (value === 'memory-knowledge') return 'memory';
  if (value === 'providers' && !providersEnabled) return 'basic';
  return visibleTabs.includes(value as SettingsTabKey) ? (value as SettingsTabKey) : 'basic';
}

export function formatSettingsNavigationSummary(
  rawValue: string | null,
  providersEnabled = false,
): string {
  const resolved = initialSettingsTab(rawValue, providersEnabled);
  return `${rawValue ?? 'null'} -> ${resolved} · providers=${providersEnabled}`;
}

export function formatSettingsNavigationJson(
  rawValue: string | null,
  providersEnabled = false,
): string {
  return JSON.stringify(
    {
      requested: rawValue,
      resolved: initialSettingsTab(rawValue, providersEnabled),
      providersEnabled,
    },
    null,
    2,
  );
}

export function auditSettingsNavigationGovernance(): {
  module: 'src/pages/settings/settingsNavigation.ts';
  phase: 'P174';
  domain: 'settings';
  legacyAliases: readonly ['general->basic', 'memory-knowledge->memory'];
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/settingsNavigation.ts',
    phase: 'P174',
    domain: 'settings',
    legacyAliases: ['general->basic', 'memory-knowledge->memory'],
    compliant:
      initialSettingsTab('general') === 'basic' &&
      initialSettingsTab('memory-knowledge') === 'memory',
  };
}
