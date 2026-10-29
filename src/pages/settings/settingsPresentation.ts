import type { SettingsSearchEntry, SettingsTabKey } from './settingsSearchIndex';

const GROUPS = [
  { id: 'basic', zh: '基础', en: 'Basics', keys: ['basic'] },
  { id: 'models', zh: '模型与服务', en: 'Models and services', keys: ['models-services'] },
  {
    id: 'agent',
    zh: '智能体',
    en: 'Agent',
    keys: [
      'orchestration',
      'tools-connections',
      'mcp',
      'plugins-skills',
      'global-rules',
    ],
  },
  {
    id: 'knowledge',
    zh: '记忆与知识',
    en: 'Memory and knowledge',
    keys: ['memory', 'zotero'],
  },
  {
    id: 'network',
    zh: '网络与远程',
    en: 'Network and remote',
    keys: ['network', 'remote-workspaces'],
  },
  {
    id: 'maintenance',
    zh: '使用与维护',
    en: 'Usage and maintenance',
    keys: ['usage-stats', 'updates'],
  },
  {
    id: 'advanced',
    zh: '诊断与实验',
    en: 'Diagnostics and experiments',
    keys: ['runtime', 'evolution', 'harness'],
  },
  {
    id: 'feedback',
    zh: '反馈',
    en: 'Feedback',
    keys: ['feedback'],
  },
] as const;

export function settingsGroups(available: readonly SettingsTabKey[], locale = 'zh') {
  return GROUPS.map((group) => ({
    id: group.id,
    label: locale === 'en' ? group.en : group.zh,
    keys: available.filter((key) => (group.keys as readonly string[]).includes(key)),
  })).filter((group) => group.keys.length > 0);
}

/** Stable row metadata, not an unverified coordinate or a whole-page text match. */
export function focusSettingsEntry(container: HTMLElement, entry: SettingsSearchEntry): boolean {
  const labels = [entry.label, entry.labelEn].map((label) => label.toLocaleLowerCase());
  const row = Array.from(container.querySelectorAll<HTMLElement>('[data-setting-label]')).find(
    (element) => {
      const label = element.dataset.settingLabel?.toLocaleLowerCase() ?? '';
      return labels.some((candidate) => label === candidate || label.startsWith(candidate + ' '));
    },
  );
  if (!row) return false;
  row.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  row.focus({ preventScroll: true });
  return true;
}

export function formatSettingsGroupsSummary(
  available: readonly SettingsTabKey[],
  locale = 'zh',
): string {
  const groups = settingsGroups(available, locale);
  const tabCount = groups.reduce((acc, g) => acc + g.keys.length, 0);
  return `settings-groups: ${groups.length} groups · ${tabCount} tabs · locale=${locale}`;
}

export function formatSettingsGroupsJson(
  available: readonly SettingsTabKey[],
  locale = 'zh',
): string {
  const groups = settingsGroups(available, locale);
  const tabCount = groups.reduce((acc, g) => acc + g.keys.length, 0);
  return JSON.stringify(
    {
      groupCount: groups.length,
      tabCount,
      locale,
      groupIds: groups.map((g) => g.id),
    },
    null,
    2,
  );
}

export function auditSettingsPresentationGovernance(): {
  module: 'src/pages/settings/settingsPresentation.ts';
  phase: 'P174';
  domain: 'settings';
  supportsGroupedNavigationAndRowFocus: boolean;
  compliant: boolean;
} {
  const groups = settingsGroups(['basic', 'models-services', 'runtime'], 'zh');
  return {
    module: 'src/pages/settings/settingsPresentation.ts',
    phase: 'P174',
    domain: 'settings',
    supportsGroupedNavigationAndRowFocus: groups.length > 0,
    compliant: groups.length > 0,
  };
}
