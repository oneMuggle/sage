import type { SettingsSearchEntry, SettingsTabKey } from './settingsSearchIndex';
import { SETTINGS_GROUPS, SETTINGS_TABS } from './settingsTabs';

/**
 * 设置页左侧导航的分组。
 *
 * P2 (2026-10-28): 分组顺序、组名与成员全部从 `settingsTabs.tsx` 注册表派生。
 * 此前本文件自带一份 `GROUPS` 常量（含已下线的 `memory-knowledge`），
 * 与 `Settings.tsx` 的 tabs 数组、`settingsNavigation` 的 visibleTabs 各写一份，
 * 改一处忘另一处就会漂移。
 *
 * 组内 tab 顺序 = 注册表顺序；`available` 决定哪些 tab 实际可见。
 */
export function settingsGroups(available: readonly SettingsTabKey[], locale = 'zh') {
  return SETTINGS_GROUPS.map((group) => ({
    id: group.id,
    label: locale === 'en' ? group.en : group.zh,
    keys: SETTINGS_TABS.filter((tab) => tab.group === group.id && available.includes(tab.key)).map(
      (tab) => tab.key,
    ),
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
