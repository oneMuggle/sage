/**
 * 设置项搜索索引 (R41 升级: 从"只搜 tab 名"到"搜到具体设置项")。
 *
 * 每个条目对应设置页一个可见控件/分组，keywords 为小写搜索词
 * (中英混排，命中时任一子串包含即可)。新增设置项时在此登记一行，
 * 设置页搜索即可发现它。
 *
 * P2 (2026-10-28): `SettingsTabKey` 迁到 `settingsTabs.tsx` 注册表 —— 用
 * `import type` 引入，编译期擦除，本模块不因此拖入 tab 组件
 * （`CommandPalette` 直接 import 本模块，不能因此把整个设置页打进包里）。
 */

import { SETTINGS_SEARCH_INDEX, type SettingsSearchEntry } from './settingsSearchEntries';

export { SETTINGS_SEARCH_INDEX, type SettingsSearchEntry } from './settingsSearchEntries';
export type { SettingsTabKey } from './settingsTabs';

export function searchSettings(query: string): SettingsSearchEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const terms = q.split(/\s+/).filter(Boolean);
  return SETTINGS_SEARCH_INDEX.filter((entry) => {
    const haystack = `${entry.keywords} ${entry.label} ${entry.labelEn} ${entry.key}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}

export function formatSettingsSearchSummary(query: string): string {
  const hits = searchSettings(query);
  const tabs = Array.from(new Set(hits.map((h) => h.tab)));
  return `query="${query.trim()}" · hits=${hits.length} · tabs=[${tabs.join(',')}]`;
}

export function formatSettingsSearchJson(query: string): string {
  const hits = searchSettings(query);
  return JSON.stringify(
    {
      query: query.trim(),
      totalIndexSize: SETTINGS_SEARCH_INDEX.length,
      hitCount: hits.length,
      keys: hits.map((h) => h.key),
      tabs: Array.from(new Set(hits.map((h) => h.tab))),
    },
    null,
    2,
  );
}

export function auditSettingsSearchIndexGovernance(): {
  module: 'src/pages/settings/settingsSearchIndex.ts';
  phase: 'P174';
  domain: 'settings';
  indexSize: number;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/settingsSearchIndex.ts',
    phase: 'P174',
    domain: 'settings',
    indexSize: SETTINGS_SEARCH_INDEX.length,
    compliant: SETTINGS_SEARCH_INDEX.length > 0,
  };
}
