/**
 * English translations (aggregator entry, domain dictionaries under ./locales/en/)
 */
import { enChatAndSider } from './locales/en/chatAndSider';
import { enSettingsAndModels } from './locales/en/settingsAndModels';
import { enWorkspaceAndTools } from './locales/en/workspaceAndTools';
import { pausedMemoryEn } from './pausedMemory';
import type { TranslationKey } from './zh';

export const en: Record<TranslationKey, string> = {
  ...enChatAndSider,
  ...enSettingsAndModels,
  ...enWorkspaceAndTools,
  ...pausedMemoryEn,
};
