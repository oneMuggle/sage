/**
 * 中文翻译 — 默认语言
 *
 * 键使用点分隔的命名空间: sidebar.new_chat, chat.title, settings.general ...
 */
export const zh = {
  // ─── 侧边栏 ───────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': '对话',
  'sidebar.nav.memory': '记忆',
  'sidebar.nav.knowledge': '知识库',
  'sidebar.nav.agents': '智能体',
  'sidebar.nav.skills': '技能',
  'sidebar.nav.settings': '设置',
  'sidebar.recent': '最近对话',
  'sidebar.new_chat': '新对话',
  'sidebar.status.connected': '已连接',
  'sidebar.status.not_configured': '未配置',
  'sidebar.status.error': '连接失败',
  'sidebar.status.latency': '延迟',
  'sidebar.empty': '暂无对话记录',

  // ─── 聊天页 ───────────────────────
  'chat.title': '对话',
  'chat.new_session': '+ 新对话',
  'chat.placeholder': '输入消息...',
  'chat.send': '发送',
  'chat.stop': '停止',
  'chat.config_warning': '未配置 API 端点或对话模型',
  'chat.config_warning_action': '前往设置',
  'chat.loading': '正在加载对话...',
  'chat.welcome': '欢迎使用 Sage',
  'chat.welcome_sub': '开始一段新对话吧',
  'chat.hint':
    'Sage 会记住你的项目信息，无需重复说明上下文 · 支持 Markdown 语法 · 点击知识库按钮多选文档作为上下文引用',
  'chat.memory_applied': '条记忆已应用',
  'chat.copy': '复制',
  'chat.copied': '已复制',
  'chat.delete_confirm': '确定要删除这个会话吗？',

  // ─── 文件上传 ─────────────────────
  'chat.drop_files': '拖放文件到此处',
  'chat.attach_image': '插入图片',
  'chat.attach_file': '附加文件',
  'chat.knowledge_ref': '引用知识库',
  'chat.knowledge_docs': '引用知识库文档',

  // ─── Slash 命令 ───────────────────
  'slash.help': '帮助',
  'slash.help_desc': '显示可用命令列表',
  'slash.clear': '清空对话',
  'slash.clear_desc': '清空当前会话的所有消息',
  'slash.search': '搜索',
  'slash.search_desc': '使用 /search 后输入搜索内容',
  'slash.summarize': '总结',
  'slash.summarize_desc': '总结当前对话内容',
  'slash.translate': '翻译',
  'slash.translate_desc': '翻译上一条消息',
  'slash.compact': '压缩上下文',
  'slash.compact_desc': '压缩当前对话上下文',

  // ─── 命令面板 ─────────────────────
  'cmd.title': '命令面板',
  'cmd.placeholder': '输入命令或搜索...',
  'cmd.empty': '无匹配结果',
  'cmd.nav': '导航',
  'cmd.actions': '操作',
  'cmd.sessions': '最近会话',
  'cmd.new_chat': '新建对话',
  'cmd.new_chat_desc': '创建一个新的对话会话',
  'cmd.toggle_theme': '切换主题',
  'cmd.toggle_theme_desc': '在亮色/暗色之间切换',
  'cmd.hint_nav': '↑↓ 导航',
  'cmd.hint_select': '↵ 选择',
  'cmd.hint_close': 'esc 关闭',
  'cmd.messages': '条消息',

  // ─── 设置页 ───────────────────────
  'settings.title': '设置',
  'settings.tab.general': '通用',
  'settings.tab.endpoints': '端点',
  'settings.tab.models': '模型',
  'settings.tab.memory': '记忆',
  'settings.tab.network': '网络',
  'settings.tab.evolution': '进化',
  'settings.section.theme': '主题',
  'settings.section.appearance': '外观',
  'settings.section.chat': '对话',
  'settings.section.data': '数据',

  // ─── 装饰主题 ─────────────────────
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
  'common.skip_to_content': '跳到主内容',
  'common.delete': '删除',
  'common.cancel': '取消',
  'common.confirm': '确定',
  'common.save': '保存',
  'common.loading': '加载中...',
  'common.error': '出错',
  'common.retry': '重试',

  // ─── 导航 ──────────────────────────
  'nav.back': '后退',
  'nav.forward': '前进',

  // ─── 时间分组 ─────────────────────
  'time.today': '今天',
  'time.yesterday': '昨天',
  'time.this_week': '本周',
  'time.earlier': '更早',

  // ─── 侧边栏分组 ─────────────────────
  'sider.section.conversations': '会话',
  'sider.section.cron': '定时任务',
  'sider.section.project': '项目',
  'sider.section.team': '团队',
  'sider.drag_handle': '拖拽排序',
  'sider.collapse': '折叠',
  'sider.expand': '展开',

  // ─── 标题栏 ──────────────────────────
  'titlebar.minimize': '最小化',
  'titlebar.maximize': '最大化',
  'titlebar.close': '关闭',

  // ─── 反馈 ──────────────────────────
  'feedback.button': '反馈',
  'feedback.title': '发送反馈',
  'feedback.screenshot': '截图预览',
  'feedback.description': '描述',
  'feedback.description_placeholder': '请描述您的问题或建议...',
  'feedback.email': '邮箱（可选）',
  'feedback.email_placeholder': 'your@email.com',
  'feedback.submit': '提交',
  'feedback.success': '感谢您的反馈！',

  // ─── @文件提及 ─────────────────────
  'chat.atFile.searching': '搜索中…',
  'chat.atFile.empty': '未找到文件',
  'chat.atFile.timeout': '搜索超时',
  'chat.atFile.error': '搜索失败',
  'chat.atFile.retry': '重试',

  // ─── /btw 补充消息 ────────────────
  'chat.btw.title': '补充问题',
  'chat.btw.placeholder': '在主任务运行时提问…',
  'chat.btw.loading': '思考中…',
  'chat.btw.error': '加载失败',
  'chat.btw.close': '关闭',

  // ─── 欢迎屏 ────────────────────────
  'welcome.hero.greeting': '你好，我是 Claude',
  'welcome.hero.subtitle': '有什么可以帮你的？',
  'welcome.hero.back': '返回',
  'welcome.input.placeholder': '输入消息，Enter 发送',
  'welcome.rec.title': '推荐助手',
  'welcome.rec.code.title': '写代码',
  'welcome.rec.code.desc': '帮我写代码、解释代码、找 Bug',
  'welcome.rec.search.title': '搜索',
  'welcome.rec.search.desc': '查找资料、查文档、找答案',
  'welcome.rec.idea.title': '创意',
  'welcome.rec.idea.desc': '脑暴点子、起名、写文案',
  'welcome.quick.feedback': '反馈',
  'welcome.quick.feedback_desc': '提交问题或建议',
  'welcome.quick.github': 'GitHub',
  'welcome.quick.github_desc': '查看源码',
  'welcome.quick.webui': 'WebUI',
  'welcome.quick.webui_desc': '在浏览器中打开',
  'welcome.quick.webui_unavailable': 'Unavailable',
} as const;

export type TranslationKey = keyof typeof zh;
