/**
 * 桌宠设置文案（win7 同步新增）。
 *
 * 与主分支把 settings.pet.* 放在 chatAndSider 不同，win7 侧独立成域模块，
 * 避免继续推高 chatAndSider 行数；聚合入口见 ../../zh.ts。
 */
export const zhPet = {
  'settings.tab.pet': '桌宠',
  'settings.pet.title': '桌面宠物',
  'settings.pet.desc':
    '让大肥鱼在桌面上显示 Sage 的工作状态：思考、调用工具、等待审批、完成或出错。',
  'settings.pet.desktop_only': '桌宠仅在桌面端可用。',
  'settings.pet.enabled': '启用桌宠',
  'settings.pet.enabled_desc': '透明置顶小窗；不读取屏幕内容，也不额外调用模型。',
  'settings.pet.display_mode': '显示位置',
  'settings.pet.display.desktop': '仅在桌面',
  'settings.pet.display.in_app': '仅在应用内',
  'settings.pet.display.both': '桌面和应用内',
  'settings.pet.display.off': '不显示',
  'settings.pet.size': '大小',
  'settings.pet.size.mini': '迷你',
  'settings.pet.size.small': '小',
  'settings.pet.size.medium': '中',
  'settings.pet.size.large': '大',
  'settings.pet.size.huge': '特大',
  'settings.pet.tempo': '待机节奏',
  'settings.pet.tempo.quiet': '安静',
  'settings.pet.tempo.standard': '标准',
  'settings.pet.tempo.lively': '活泼',
  'settings.pet.bubble': '气泡提示',
  'settings.pet.bubble.important': '仅重要状态',
  'settings.pet.bubble.always': '常驻',
  'settings.pet.bubble.off': '隐藏',
  'settings.pet.reduce_motion': '减少动态',
  'settings.pet.show_session_title': '气泡显示会话名',
  'settings.pet.sound_waiting': '等待审批提示音',
  'settings.pet.sound_error': '工具出错提示音',
  'settings.pet.sound_done': '对话完成提示音',
  'settings.pet.compatibility': '兼容模式',
  'settings.pet.compatibility_desc': 'Win7 无 Aero 或远程桌面下，使用不透明窗口并关闭点击穿透。',
  'settings.pet.compat.auto': '自动',
  'settings.pet.compat.on': '开启',
  'settings.pet.compat.off': '关闭',
  'settings.pet.reset_position': '回到初始位置',
  'settings.pet.asset_notice': '素材来自 dsh-pet（MIT）；完整动画包随安装包分发。',
} as const;
