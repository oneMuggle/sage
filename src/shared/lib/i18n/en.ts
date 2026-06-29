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

  // ─── Scheduled Tasks (M3) ──────────
  'scheduled.title': 'Scheduled Tasks',
  'scheduled.subtitle': 'Manage automated messages',
  'scheduled.empty': 'No scheduled tasks yet — create one below.',
  'scheduled.create': 'New Task',
  'scheduled.edit': 'Edit Task',
  'scheduled.field.name': 'Task Name',
  'scheduled.field.type': 'Type',
  'scheduled.field.type.once': 'One-time',
  'scheduled.field.type.recurring': 'Recurring',
  'scheduled.field.cron': 'Cron Expression',
  'scheduled.field.at': 'Execution Time',
  'scheduled.field.session': 'Target Session',
  'scheduled.field.content': 'Message content',
  'scheduled.field.enabled': 'Enabled',
  'scheduled.status.enabled': 'Enabled',
  'scheduled.status.disabled': 'Disabled',
  'scheduled.action.run_now': 'Run now',
  'scheduled.toast.create_fail': 'Creation failed',
  'scheduled.toast.update_fail': 'Update failed',
  'scheduled.toast.delete_fail': 'Delete failed',
  'scheduled.confirm.delete': 'Delete this scheduled task?',
  'scheduled.sidebar.title': 'Scheduled Tasks',

  // ─── Cron Presets (M3) ─────────────
  'cron.preset.hourly': 'Hourly',
  'cron.preset.daily08': 'Daily 08:00',
  'cron.preset.daily18': 'Daily 18:00',
  'cron.preset.weekday09': 'Weekdays 09:00',
  'cron.preset.weeklyMon': 'Weekly Mon 09:00',
  'cron.preset.monthly1st': 'Monthly 1st 09:00',

  // ─── Common ────────────────────────
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',
  'common.delete': 'Delete',

  // ─── Sidebar sections ─────────────
  'sider.section.conversations': 'Conversations',
  'sider.section.cron': 'Scheduled Tasks',
  'sider.section.project': 'Projects',
  'sider.section.team': 'Team',
  'sider.drag_handle': 'Drag to reorder',
  'sider.collapse': 'Collapse',
  'sider.expand': 'Expand',

  // ─── Welcome screen ──────────────
  'welcome.hero.greeting': "Hi, I'm Sage",
  'welcome.hero.subtitle': 'How can I help you today?',
  'welcome.hero.back': 'Back',
  'welcome.input.placeholder': 'Type a message, press Enter to send',
  'welcome.rec.title': 'Recommended assistants',
  'welcome.rec.code.title': 'Write code',
  'welcome.rec.code.desc': 'Help me write, explain, or debug code',
  'welcome.rec.search.title': 'Search',
  'welcome.rec.search.desc': 'Look up info, docs, or answers',
  'welcome.rec.idea.title': 'Brainstorm',
  'welcome.rec.idea.desc': 'Generate ideas, names, or copy',
  'welcome.quick.feedback': 'Feedback',
  'welcome.quick.feedback_desc': 'Submit an issue or suggestion',
  'welcome.quick.github': 'GitHub',
  'welcome.quick.github_desc': 'View source code',
  'welcome.quick.webui': 'WebUI',
  'welcome.quick.webui_desc': 'Open in browser',
  'welcome.quick.webui_unavailable': 'Unavailable',
};
