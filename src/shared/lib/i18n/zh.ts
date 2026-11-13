/**
 * 中文翻译 — 默认语言（聚合入口，分域词典位于 ./locales/zh/）
 */
import { zhAttachmentStatus } from './locales/zh/attachmentStatus';
import { zhChatAndSider } from './locales/zh/chatAndSider';
import { zhChatDisplayMode } from './locales/zh/chatDisplayMode';
import { zhChatPdfOcr } from './locales/zh/chatPdfOcr';
import { zhChatSteerStaging } from './locales/zh/chatSteerStaging';
import { zhContextMenu } from './locales/zh/contextMenu';
import { zhDesign } from './locales/zh/design';
import { zhGovernanceFiles } from './locales/zh/governanceFiles';
import { zhPetPack } from './locales/zh/petPack';
import { zhPlaybook } from './locales/zh/playbook';
import { zhRules } from './locales/zh/rules';
import { zhSettingsAndModels } from './locales/zh/settingsAndModels';
import { zhSettingsUi } from './locales/zh/settingsUi';
import { zhTaskCenter } from './locales/zh/taskCenter';
import { zhWorkspaceAndTools } from './locales/zh/workspaceAndTools';
import { pausedMemoryZh } from './pausedMemory';
import { retryBannerZh } from './retryBanner';

export const zh = {
  ...zhChatAndSider,
  ...zhAttachmentStatus,
  ...zhChatDisplayMode,
  ...zhChatPdfOcr,
  ...zhChatSteerStaging,
  ...zhContextMenu,
  ...zhDesign,
  ...zhGovernanceFiles,
  ...zhPetPack,
  ...zhPlaybook,
  ...zhRules,
  ...zhSettingsAndModels,
  ...zhSettingsUi,
  ...zhTaskCenter,
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
