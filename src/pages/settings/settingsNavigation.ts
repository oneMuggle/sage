import type { SettingsTabKey } from './settingsSearchIndex';

const visibleTabs: readonly SettingsTabKey[] = [
  'basic',
  'tools-connections',
  'models-services',
  'orchestration',
  'memory',
  'network',
  'mcp',
  'plugins-skills',
  'remote-workspaces',
  'zotero',
  'runtime',
  'evolution',
  'harness',
  'updates',
  'usage-stats',
  // G1 (2026-10-27): 全局规则 Tab（~/.sage/SAGE.md 读写）
  'global-rules',
  // 2026-10-29: 用户反馈 Tab（管理员转发 + 双向会话）
  'feedback',
];

/** Keep old settings bookmarks, never render an unknown/hidden initial tab. */
export function initialSettingsTab(value: string | null, _providersEnabled = false): SettingsTabKey {
  if (value === 'general') return 'basic';
  // 上游把「记忆与知识」tab 重命名为 memory；旧书签按别名迁回，不落到 basic。
  if (value === 'memory-knowledge') return 'memory';
  // P1-b: 端点/模型/更新源合并为 models-services；旧书签迁到默认 models 子 tab。
  if (value === 'endpoints' || value === 'models' || value === 'providers') return 'models-services';
  // P1-b: 插件/技能合并为 plugins-skills；旧书签迁到默认 plugins 子 tab。
  if (value === 'plugins' || value === 'skills') return 'plugins-skills';
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
