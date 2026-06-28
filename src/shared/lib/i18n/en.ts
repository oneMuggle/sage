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

  // ─── Settings ─────────────────────
  'settings.section.theme': 'Theme',

  // ─── Theme ───────────────────────
  'theme.name.mint_blue': 'Mint Blue',
  'theme.name.sakura': 'Sakura',
  'theme.name.cyber_neon': 'Cyber Neon',
  'theme.name.midnight_amber': 'Midnight Amber',
  'theme.name.parchment': 'Parchment',
  'theme.desc.mint_blue': 'Refreshing mint green tones, gentle on the eyes',
  'theme.desc.sakura': 'Soft cherry blossom pink, spring romance',
  'theme.desc.cyber_neon': 'Neon purple and pink, futuristic vibe',
  'theme.desc.midnight_amber':
    'Dark background with amber highlights, easy on the eyes for long reads',
  'theme.desc.parchment': 'Vintage parchment texture, ideal for writing',
  'theme.gallery.section_basic': 'Basic',
  'theme.gallery.section_decorative': 'Decorative',

  // ─── Scheduled Tasks ──────────────
  'scheduled.create': 'Create Scheduled Task',
  'scheduled.edit': 'Edit Scheduled Task',
  'scheduled.field.name': 'Task Name',
  'scheduled.field.type.once': 'One-time',
  'scheduled.field.type.recurring': 'Recurring',
  'scheduled.field.cron': 'Cron Expression',
  'scheduled.field.at': 'Execution Time',
  'scheduled.field.content': 'Message content',
  'scheduled.field.enabled': 'Enabled',
  'scheduled.toast.create_fail': 'Creation failed',
  'scheduled.toast.update_fail': 'Update failed',

  // ─── Common ───────────────────────
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
};
