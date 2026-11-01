/**
 * English translations (aggregator entry, domain dictionaries under ./locales/en/)
 */
import { enChatAndSider } from './locales/en/chatAndSider';
import { enChatPdfOcr } from './locales/en/chatPdfOcr';
import { enContextMenu } from './locales/en/contextMenu';
<<<<<<< HEAD
import { enPet } from './locales/en/pet';
=======
>>>>>>> origin/main
import { enPetPack } from './locales/en/petPack';
import { enPlaybook } from './locales/en/playbook';
import { enSettingsAndModels } from './locales/en/settingsAndModels';
import { enSettingsUi } from './locales/en/settingsUi';
import { enWorkspaceAndTools } from './locales/en/workspaceAndTools';
import { pausedMemoryEn } from './pausedMemory';
import { retryBannerEn } from './retryBanner';
import type { TranslationKey } from './zh';

export const en: Record<TranslationKey, string> = {
  ...enChatAndSider,
  ...enChatPdfOcr,
  ...enContextMenu,
<<<<<<< HEAD
  ...enPet,
=======
>>>>>>> origin/main
  ...enPetPack,
  ...enPlaybook,
  ...enSettingsAndModels,
  ...enSettingsUi,
  ...enWorkspaceAndTools,
  ...pausedMemoryEn,
  ...retryBannerEn,
};

export function formatEnglishTranslationsSummary(): string {
  const keys = Object.keys(en);
  return `locale=en · keys=${keys.length}`;
}

export function formatEnglishTranslationsJson(): string {
  const keys = Object.keys(en);
  return JSON.stringify({
    locale: 'en',
    keyCount: keys.length,
    hasChatTitle: 'chat.title' in en,
  });
}

export function auditEnGovernance(): string {
  return JSON.stringify({
    module: 'en-i18n',
    phase: 'P182',
    audited: true,
  });
}
