/**
 * 中文翻译 — 主源。
 *
 * 翻译键使用点分隔命名空间：sidebar.new_chat, chat.title ...
 * 增加 key 必须先在此文件加，否则 en.ts 无法通过类型检查。
 *
 * 58 个 key（sidebar 4 + chat 6 + theme 12 + settings 1 + scheduled 28 + cron 6 + common 7）。
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

  // ─── 定时任务 (M3) ───────────────
  'scheduled.title': '定时任务',
  'scheduled.subtitle': '管理自动发送的消息',
  'scheduled.empty': '还没有定时任务，点击下方按钮创建一个。',
  'scheduled.create': '新建任务',
  'scheduled.edit': '编辑任务',
  'scheduled.field.name': '任务名称',
  'scheduled.field.type': '类型',
  'scheduled.field.type.once': '一次性',
  'scheduled.field.type.recurring': '周期性',
  'scheduled.field.cron': 'Cron 表达式',
  'scheduled.field.at': '执行时间',
  'scheduled.field.session': '目标会话',
  'scheduled.field.content': '发送内容',
  'scheduled.field.enabled': '启用',
  'scheduled.status.enabled': '已启用',
  'scheduled.status.disabled': '已停用',
  'scheduled.action.run_now': '立即执行',
  'scheduled.toast.create_fail': '创建失败',
  'scheduled.toast.update_fail': '更新失败',
  'scheduled.toast.delete_fail': '删除失败',
  'scheduled.confirm.delete': '确定要删除这个定时任务吗？',
  'scheduled.sidebar.title': '定时任务',

  // ─── Cron 预设 (M3) ───────────────
  'cron.preset.hourly': '每小时',
  'cron.preset.daily08': '每天 08:00',
  'cron.preset.daily18': '每天 18:00',
  'cron.preset.weekday09': '工作日 09:00',
  'cron.preset.weeklyMon': '每周一 09:00',
  'cron.preset.monthly1st': '每月 1 日 09:00',

  // ─── 通用 ─────────────────────────
  'common.cancel': '取消',
  'common.confirm': '确定',
  'common.save': '保存',
  'common.loading': '加载中...',
  'common.error': '出错',
  'common.retry': '重试',
  'common.delete': '删除',

  // ─── 侧边栏分组 ─────────────────────
  'sider.section.conversations': '会话',
  'sider.section.cron': '定时任务',
  'sider.section.project': '项目',
  'sider.section.team': '团队',
  'sider.drag_handle': '拖拽排序',
  'sider.collapse': '折叠',
  'sider.expand': '展开',
} as const;

export type TranslationKey = keyof typeof zh;

/** Locale 标识符：对齐 main ('zh' | 'en')。 */
export type Locale = 'zh' | 'en';
