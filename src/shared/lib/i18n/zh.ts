/**
 * 中文翻译 — 主源。
 *
 * 翻译键使用点分隔命名空间：sidebar.new_chat, chat.title ...
 * 增加 key 必须先在此文件加，否则 en.ts 无法通过类型检查。
 *
 * 29 个 key（sidebar 4 + chat 6 + theme 12 + settings 1 + common 6）。
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

  // ─── 设置 ─────────────────────────
  'settings.section.theme': '主题',

  // ─── 主题 ─────────────────────────
  'theme.name.mint_blue': '薄荷蓝',
  'theme.name.sakura': '樱花粉',
  'theme.name.cyber_neon': 'Cyber Neon',
  'theme.name.midnight_amber': '深夜琥珀',
  'theme.name.parchment': '羊皮纸',
  'theme.desc.mint_blue': '清新的薄荷绿色调，温和不刺眼',
  'theme.desc.sakura': '温柔的樱花粉色，浪漫春日感',
  'theme.desc.cyber_neon': '霓虹紫粉，未来科技感',
  'theme.desc.midnight_amber': '深色背景配琥珀高亮，长时间阅读友好',
  'theme.desc.parchment': '复古羊皮纸纹理，文学与写作场景',
  'theme.gallery.section_basic': '基础主题',
  'theme.gallery.section_decorative': '装饰主题',

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
