/**
 * 中文翻译 — 默认语言（聚合入口，分域词典位于 ./locales/zh/）
 */
import { zhChatAndSider } from './locales/zh/chatAndSider';
import { zhSettingsAndModels } from './locales/zh/settingsAndModels';
import { zhWorkspaceAndTools } from './locales/zh/workspaceAndTools';
import { pausedMemoryZh } from './pausedMemory';
import { retryBannerZh } from './retryBanner';

export const zh = {
  ...zhChatAndSider,
  ...zhSettingsAndModels,
  ...zhWorkspaceAndTools,
  ...pausedMemoryZh,
  ...retryBannerZh,
} as const;

export type TranslationKey = keyof typeof zh;
