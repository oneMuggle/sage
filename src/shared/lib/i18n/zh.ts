/**
 * 中文翻译 — 默认语言（聚合入口，分域词典位于 ./locales/zh/）
 */
import { zhChatAndSider } from './locales/zh/chatAndSider';
import { zhContextMenu } from './locales/zh/contextMenu';
import { zhSettingsAndModels } from './locales/zh/settingsAndModels';
import { zhWorkspaceAndTools } from './locales/zh/workspaceAndTools';
import { pausedMemoryZh } from './pausedMemory';
import { retryBannerZh } from './retryBanner';

export const zh = {
  ...zhChatAndSider,
  ...zhContextMenu,
  ...zhSettingsAndModels,
  ...zhWorkspaceAndTools,
  ...pausedMemoryZh,
  ...retryBannerZh,
} as const;

export type TranslationKey = keyof typeof zh;

export function formatChineseTranslationsSummary(): string {
  const keys = Object.keys(zh);
  return `locale=zh · keys=${keys.length}`;
}

export function formatChineseTranslationsJson(): string {
  const keys = Object.keys(zh);
  return JSON.stringify({
    locale: 'zh',
    keyCount: keys.length,
    hasChatTitle: 'chat.title' in zh,
  });
}

export function auditZhGovernance(): string {
  return JSON.stringify({
    module: 'zh-i18n',
    phase: 'P182',
    audited: true,
  });
}
