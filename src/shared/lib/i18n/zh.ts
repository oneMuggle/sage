/**
 * 中文翻译 — 主源。
 *
 * 翻译键使用点分隔命名空间：sidebar.new_chat, chat.title ...
 * 增加 key 必须先在此文件加，否则 en.ts 无法通过类型检查。
 *
 * 28 个 win7 当前能用的 key（sidebar 4 + chat 6 + theme 12 + common 6）。
 */

export const zh = {
  // ─── 侧边栏 ───────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': '对话',
  'sidebar.nav.settings': '设置',
  'sidebar.new_chat': '新对话',

  // ─── 聊天页 ───────────────────────
  'chat.title': '对话',
  'chat.new_session': '+ 新对话',
  'chat.placeholder': '输入消息...',
  'chat.send': '发送',
  'chat.stop': '停止',
  'chat.config_warning': '未配置 API 端点或对话模型',

  // ─── 主题 (P3 最小集,P4 补齐 cover 描述等) ───
  'theme.selector.title': '主题',
  'theme.selector.reset': '重置为默认',
  'theme.selector.custom': '自定义 CSS',
  'theme.editor.cancel': '取消',
  'theme.editor.save': '保存',
  'theme.editor.sync_failed': '同步失败',
  'theme.editor.save_failed': '保存失败',
  'theme.presets.light.name': '明亮',
  'theme.presets.dark.name': '暗黑',
  'theme.presets.ocean.name': '海洋',
  'theme.presets.forest.name': '森林',
  'theme.presets.sunset.name': '日落',

  // ─── 通用 ─────────────────────────
  'common.cancel': '取消',
  'common.confirm': '确定',
  'common.save': '保存',
  'common.loading': '加载中...',
  'common.error': '出错',
  'common.retry': '重试',
} as const;

export type TranslationKey = keyof typeof zh;

/** Locale 标识符：对齐 main ('zh' | 'en')。 */
export type Locale = 'zh' | 'en';
