/**
 * 日常浏览器扩展设置项搜索条目。
 *
 * 从 `settingsSearchEntries.ts` 拆出，避免主索引越过 800 行质量门禁。
 */

import type { SettingsSearchEntry } from './settingsSearchEntries';

export const BROWSER_EXTENSION_SETTINGS_SEARCH_ENTRIES: SettingsSearchEntry[] = [
  {
    key: 'browser_extension',
    tab: 'network',
    label: '日常浏览器扩展',
    labelEn: 'Everyday browser extension',
    keywords:
      '浏览器扩展 browser extension chrome edge 配对 pairing 共享 share 标签页 tab 登录态 日常浏览器 调试 debugger',
  },
];
