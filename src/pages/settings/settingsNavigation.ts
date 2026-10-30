import { SETTINGS_TAB_ALIASES, SETTINGS_TAB_KEYS, type SettingsTabKey } from './settingsTabs';

/**
 * Keep old settings bookmarks, never render an unknown initial tab.
 *
 * P2 (2026-10-28): 合法 tab 列表与别名迁移表都从 `settingsTabs.tsx` 注册表派生。
 * 此前本文件自带一份 `visibleTabs`、外加三行硬编码别名分支，与 `Settings.tsx`
 * 的 tabs 数组、`settingsPresentation` 的 GROUPS 各写一份 —— 改一处忘另一处
 * 就会漂移（合并 tab 时 `visibleTabs` 与别名分支就不同步过一次）。
 *
 * 注：`providers` 不再是独立 tab（P1-b 合并进 `models-services` 的子 tab），
 * 因此这里不再有 providers 开关的可见性门控。
 */
export function initialSettingsTab(value: string | null): SettingsTabKey {
  if (!value) return 'basic';
  const aliased = SETTINGS_TAB_ALIASES.get(value);
  if (aliased) return aliased;
  return SETTINGS_TAB_KEYS.includes(value as SettingsTabKey)
    ? (value as SettingsTabKey)
    : 'basic';
}

export function formatSettingsNavigationSummary(
  rawValue: string | null,
  providersEnabled = false,
): string {
  const resolved = initialSettingsTab(rawValue);
  return `${rawValue ?? 'null'} -> ${resolved} · providers=${providersEnabled}`;
}

export function formatSettingsNavigationJson(
  rawValue: string | null,
  providersEnabled = false,
): string {
  return JSON.stringify(
    {
      requested: rawValue,
      resolved: initialSettingsTab(rawValue),
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
  legacyAliases: readonly string[];
  compliant: boolean;
} {
  // 别名表从注册表派生，避免审计元数据与实际迁移行为漂移。
  const legacyAliases = Array.from(SETTINGS_TAB_ALIASES.entries()).map(
    ([alias, key]) => `${alias}->${key}`,
  );
  return {
    module: 'src/pages/settings/settingsNavigation.ts',
    phase: 'P174',
    domain: 'settings',
    legacyAliases,
    compliant:
      legacyAliases.length > 0 &&
      Array.from(SETTINGS_TAB_ALIASES.entries()).every(
        ([alias, key]) => initialSettingsTab(alias) === key,
      ),
  };
}
