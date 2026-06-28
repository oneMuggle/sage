import type { TranslationKey } from './zh';

/**
 * English translations.
 *
 * Record<TranslationKey, string> 强制要求每个 zh key 在此都有对应英文值。
 * 加 zh 新 key 后这里会编译报错，提醒补英。
 */

export const en: Record<TranslationKey, string> = {
  // ─── Sidebar ──────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': 'Chat',
  'sidebar.nav.settings': 'Settings',
  'sidebar.new_chat': 'New Chat',

  // ─── Chat ─────────────────────────
  'chat.title': 'Chat',
  'chat.new_session': '+ New Chat',
  'chat.placeholder': 'Type a message...',
  'chat.send': 'Send',
  'chat.stop': 'Stop',
  'chat.config_warning': 'API endpoint or chat model not configured',

  // ─── Common ───────────────────────
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
};
