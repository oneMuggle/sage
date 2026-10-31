/**
 * 桌宠（pet）设置项搜索条目。
 *
 * 从 `settingsSearchEntries.ts` 拆出，避免主索引越过 800 行质量门禁。
 */

import type { SettingsSearchEntry } from './settingsSearchEntries';

export const PET_SETTINGS_SEARCH_ENTRIES: SettingsSearchEntry[] = [
  {
    key: 'pet_enabled',
    tab: 'pet',
    label: '启用桌宠',
    labelEn: 'Enable desktop pet',
    keywords: 'pet 桌宠 宠物 大肥鱼 desktop pet companion 状态',
  },
  {
    key: 'pet_display_mode',
    tab: 'pet',
    label: '桌宠显示位置',
    labelEn: 'Pet display mode',
    keywords: 'pet 桌宠 显示 位置 desktop in-app off',
  },
  {
    key: 'pet_size',
    tab: 'pet',
    label: '桌宠大小',
    labelEn: 'Pet size',
    keywords: 'pet 桌宠 大小 size mini small medium large huge',
  },
  {
    key: 'pet_tempo',
    tab: 'pet',
    label: '桌宠待机节奏',
    labelEn: 'Pet idle tempo',
    keywords: 'pet 桌宠 节奏 tempo quiet standard lively 待机',
  },
];
