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

  // ─── Theme (P3 minimum set; P4 will expand) ──
  'theme.selector.title': 'Theme',
  'theme.selector.reset': 'Reset to default',
  'theme.selector.custom': 'Custom CSS',
  'theme.editor.cancel': 'Cancel',
  'theme.editor.save': 'Save',
  'theme.editor.sync_failed': 'Sync failed',
  'theme.editor.save_failed': 'Save failed',
  'theme.presets.light.name': 'Light',
  'theme.presets.dark.name': 'Dark',
  'theme.presets.ocean.name': 'Ocean',
  'theme.presets.forest.name': 'Forest',
  'theme.presets.sunset.name': 'Sunset',

  // ─── Common ───────────────────────
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
};
