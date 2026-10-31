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
    key: 'pet_pets',
    tab: 'pet',
    label: '宠物列表与大小',
    labelEn: 'Pets and sizes',
    keywords:
      'pet 桌宠 宠物 多宠物 大小 size mini small medium large huge 动画包 pack 添加 add 移除 remove',
  },
  {
    key: 'pet_tempo',
    tab: 'pet',
    label: '桌宠待机节奏',
    labelEn: 'Pet idle tempo',
    keywords: 'pet 桌宠 节奏 tempo quiet standard lively 待机',
  },
  {
    key: 'pet_pack_manage',
    tab: 'pet',
    label: '动画包导入导出',
    labelEn: 'Import and export pet packs',
    keywords: 'pet 桌宠 动画包 pack zip 导入 导出 删除 import export delete',
  },
<<<<<<< HEAD
=======
  {
    key: 'pet_external_api',
    tab: 'pet',
    label: '本地只读状态 API',
    labelEn: 'Local read-only status API',
    keywords: 'pet 桌宠 api http 127.0.0.1 token 插件 plugin 状态 status 只读 readonly',
  },
>>>>>>> origin/main
];
