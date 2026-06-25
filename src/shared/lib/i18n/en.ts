/**
 * English translations
 */
import type { TranslationKey } from './zh';

export const en: Record<TranslationKey, string> = {
  // ─── Sidebar ──────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': 'Chat',
  'sidebar.nav.memory': 'Memory',
  'sidebar.nav.knowledge': 'Knowledge',
  'sidebar.nav.agents': 'Agents',
  'sidebar.nav.skills': 'Skills',
  'sidebar.nav.settings': 'Settings',
  'sidebar.recent': 'Recent Chats',
  'sidebar.new_chat': 'New Chat',
  'sidebar.status.connected': 'Connected',
  'sidebar.status.not_configured': 'Not configured',
  'sidebar.status.error': 'Connection failed',
  'sidebar.status.latency': 'Latency',
  'sidebar.empty': 'No chat history',

  // ─── Chat ─────────────────────────
  'chat.title': 'Chat',
  'chat.new_session': '+ New Chat',
  'chat.placeholder': 'Type a message...',
  'chat.send': 'Send',
  'chat.stop': 'Stop',
  'chat.config_warning': 'API endpoint or chat model not configured',
  'chat.config_warning_action': 'Go to Settings',
  'chat.loading': 'Loading conversation...',
  'chat.welcome': 'Welcome to Sage',
  'chat.welcome_sub': 'Start a new conversation',
  'chat.hint':
    'Sage remembers your project context · Supports Markdown · Click Knowledge to attach documents',
  'chat.memory_applied': 'memories applied',
  'chat.copy': 'Copy',
  'chat.copied': 'Copied',
  'chat.delete_confirm': 'Are you sure you want to delete this session?',

  // ─── File upload ──────────────────
  'chat.drop_files': 'Drop files here',
  'chat.attach_image': 'Attach image',
  'chat.attach_file': 'Attach file',
  'chat.knowledge_ref': 'Reference knowledge',
  'chat.knowledge_docs': 'Reference knowledge documents',

  // ─── Slash commands ───────────────
  'slash.help': 'Help',
  'slash.help_desc': 'Show available commands',
  'slash.clear': 'Clear chat',
  'slash.clear_desc': 'Clear all messages in current session',
  'slash.search': 'Search',
  'slash.search_desc': 'Type after /search to search',
  'slash.summarize': 'Summarize',
  'slash.summarize_desc': 'Summarize current conversation',
  'slash.translate': 'Translate',
  'slash.translate_desc': 'Translate the last message',
  'slash.compact': 'Compact context',
  'slash.compact_desc': 'Compress conversation context',

  // ─── Command palette ──────────────
  'cmd.title': 'Command Palette',
  'cmd.placeholder': 'Type a command or search...',
  'cmd.empty': 'No matching results',
  'cmd.nav': 'Navigation',
  'cmd.actions': 'Actions',
  'cmd.sessions': 'Recent Sessions',
  'cmd.new_chat': 'New Chat',
  'cmd.new_chat_desc': 'Create a new chat session',
  'cmd.toggle_theme': 'Toggle Theme',
  'cmd.toggle_theme_desc': 'Switch between light and dark',
  'cmd.hint_nav': '↑↓ Navigate',
  'cmd.hint_select': '↵ Select',
  'cmd.hint_close': 'esc Close',
  'cmd.messages': 'messages',

  // ─── Settings ─────────────────────
  'settings.title': 'Settings',
  'settings.tab.general': 'General',
  'settings.tab.endpoints': 'Endpoints',
  'settings.tab.models': 'Models',
  'settings.tab.memory': 'Memory',
  'settings.tab.network': 'Network',
  'settings.tab.evolution': 'Evolution',
  'settings.section.theme': 'Theme',
  'settings.section.appearance': 'Appearance',
  'settings.section.chat': 'Chat',
  'settings.section.data': 'Data',

  // ─── Common ───────────────────────
  'common.skip_to_content': 'Skip to content',
  'common.delete': 'Delete',
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',

  // ─── Navigation ─────────────────────
  'nav.back': 'Back',
  'nav.forward': 'Forward',

  // ─── Time groups ──────────────────
  'time.today': 'Today',
  'time.yesterday': 'Yesterday',
  'time.this_week': 'This Week',
  'time.earlier': 'Earlier',

  // ─── Sidebar sections ─────────────
  'sider.section.conversations': 'Conversations',
  'sider.section.cron': 'Scheduled Tasks',
  'sider.section.project': 'Projects',
  'sider.section.team': 'Team',
  'sider.drag_handle': 'Drag to reorder',
  'sider.collapse': 'Collapse',
  'sider.expand': 'Expand',
};
