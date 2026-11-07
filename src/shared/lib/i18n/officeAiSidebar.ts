/**
 * AI 文档工作台侧栏文案（P2）。
 *
 * 独立成模块：locales/{en,zh}/chatAndSider.ts 已在 architecture-baseline.json
 * 基线上（806/807 行），新文案放这里不让基线文件继续增长。
 */
export const officeAiSidebarZh = {
  // Sidebar chrome
  'office.ai.sidebar.title': 'AI 助手',
  'office.ai.sidebar.open': '打开 AI 助手',
  'office.ai.sidebar.close': '关闭 AI 助手',
  'office.ai.sidebar.empty': '选中文本或输入指令开始',
  'office.ai.sidebar.no_document': '未选择文档',
  'office.ai.sidebar.current_document': '当前文档',
  'office.ai.sidebar.placeholder': '输入指令，/ 唤起命令',
  'office.ai.sidebar.send': '发送',
  'office.ai.sidebar.thinking': '生成中…',
  'office.ai.sidebar.copy': '复制',
  'office.ai.sidebar.copied': '已复制',
  'office.ai.sidebar.apply': '应用到文档',
  'office.ai.sidebar.apply_disabled': '仅 Word 文档支持应用',
  'office.ai.sidebar.apply_path_invalid': '无法应用：文档路径不可用',
  'office.ai.sidebar.discard': '丢弃',
  'office.ai.sidebar.retry': '重试',
  'office.ai.sidebar.apply_failed': '应用失败：{message}',
  'office.ai.sidebar.request_failed': '请求失败：{message}',
  'office.ai.sidebar.apply_done': '已写入修订痕迹',
  'office.ai.sidebar.unknown_command': '未知命令：{command}',
  'office.ai.revise.default_message': 'AI 改写',

  // Selection toolbar
  'office.ai.selection.rewrite': '改写润色',
  'office.ai.selection.chat': '就这段提问',
  'office.ai.selection.edit': '按指令修改',
  'office.ai.selection.audit': '审校建议',
  'office.ai.selection.dismiss': '取消',
  'office.ai.selection.toolbarLabel': '选区操作',

  // Quick commands — documents
  'office.ai.quick.documents.audit': '审校全文',
  'office.ai.quick.documents.rules': '提取规则',
  'office.ai.quick.documents.summary': '生成摘要',
  'office.ai.quick.documents.translate': '翻译',

  // Quick commands — generate
  'office.ai.quick.generate.expand': '从摘要扩展',
  'office.ai.quick.generate.structure': '优化结构',
  'office.ai.quick.generate.details': '补充细节',
  'office.ai.quick.generate.consistency': '检查一致性',

  // Quick commands — rules
  'office.ai.quick.rules.extract': '提取规则',
  'office.ai.quick.rules.conflicts': '检查冲突',
  'office.ai.quick.rules.merge': '合并相似',

  // Quick commands — latex
  'office.ai.quick.latex.compile': '编译检查',
  'office.ai.quick.latex.citations': '引用格式化',
  'office.ai.quick.latex.formulas': '公式校对',

  // Audit card
  'office.ai.audit.title': '审校建议',
  'office.ai.audit.apply_all': '应用全部可修复项',
  'office.ai.audit.skip': '跳过',
  'office.ai.audit.applied': '已应用',
  'office.ai.audit.skipped': '已跳过',
  'office.ai.audit.paragraph': '第 {index} 段',
  'office.ai.audit.apply_skipped': '已应用部分建议，{count} 条被跳过',

  // Edit card
  'office.ai.edit.title': '指令式修改',
  'office.ai.edit.hint': '描述要怎么改，AI 会定位段落',
  'office.ai.edit.no_match': '没有找到需要修改的段落',
  'office.ai.edit.prefix': '把这段改成：',
  'office.ai.edit.rewrite': '改写',
  'office.ai.edit.polish': '润色',
  'office.ai.edit.expand': '扩写',
  'office.ai.edit.condense': '缩写',
} as const;

export const officeAiSidebarEn: Record<keyof typeof officeAiSidebarZh, string> = {
  // Sidebar chrome
  'office.ai.sidebar.title': 'AI Assistant',
  'office.ai.sidebar.open': 'Open AI assistant',
  'office.ai.sidebar.close': 'Close AI assistant',
  'office.ai.sidebar.empty': 'Select text or type a command to start',
  'office.ai.sidebar.no_document': 'No document selected',
  'office.ai.sidebar.current_document': 'Current document',
  'office.ai.sidebar.placeholder': 'Type an instruction, / for commands',
  'office.ai.sidebar.send': 'Send',
  'office.ai.sidebar.thinking': 'Generating…',
  'office.ai.sidebar.copy': 'Copy',
  'office.ai.sidebar.copied': 'Copied',
  'office.ai.sidebar.apply': 'Apply to document',
  'office.ai.sidebar.apply_disabled': 'Only Word documents support applying',
  'office.ai.sidebar.apply_path_invalid': 'Cannot apply: document path unavailable',
  'office.ai.sidebar.discard': 'Discard',
  'office.ai.sidebar.retry': 'Retry',
  'office.ai.sidebar.apply_failed': 'Apply failed: {message}',
  'office.ai.sidebar.request_failed': 'Request failed: {message}',
  'office.ai.sidebar.apply_done': 'Applied as tracked changes',
  'office.ai.sidebar.unknown_command': 'Unknown command: {command}',
  'office.ai.revise.default_message': 'AI rewrite',

  // Selection toolbar
  'office.ai.selection.rewrite': 'Rewrite',
  'office.ai.selection.chat': 'Ask about this',
  'office.ai.selection.edit': 'Edit by instruction',
  'office.ai.selection.audit': 'Audit',
  'office.ai.selection.dismiss': 'Dismiss',
  'office.ai.selection.toolbarLabel': 'Selection actions',

  // Quick commands — documents
  'office.ai.quick.documents.audit': 'Audit document',
  'office.ai.quick.documents.rules': 'Extract rules',
  'office.ai.quick.documents.summary': 'Summarize',
  'office.ai.quick.documents.translate': 'Translate',

  // Quick commands — generate
  'office.ai.quick.generate.expand': 'Expand from summary',
  'office.ai.quick.generate.structure': 'Improve structure',
  'office.ai.quick.generate.details': 'Add detail',
  'office.ai.quick.generate.consistency': 'Check consistency',

  // Quick commands — rules
  'office.ai.quick.rules.extract': 'Extract rules',
  'office.ai.quick.rules.conflicts': 'Check conflicts',
  'office.ai.quick.rules.merge': 'Merge similar rules',

  // Quick commands — latex
  'office.ai.quick.latex.compile': 'Check build',
  'office.ai.quick.latex.citations': 'Format citations',
  'office.ai.quick.latex.formulas': 'Proofread formulas',

  // Audit card
  'office.ai.audit.title': 'Audit suggestions',
  'office.ai.audit.apply_all': 'Apply all fixable',
  'office.ai.audit.skip': 'Skip',
  'office.ai.audit.applied': 'Applied',
  'office.ai.audit.skipped': 'Skipped',
  'office.ai.audit.paragraph': 'Paragraph {index}',
  'office.ai.audit.apply_skipped': 'Some suggestions were skipped ({count})',

  // Edit card
  'office.ai.edit.title': 'Instruction edit',
  'office.ai.edit.hint': 'Describe the change; AI locates the paragraph',
  'office.ai.edit.no_match': 'No paragraph matched the instruction',
  'office.ai.edit.prefix': 'Change this to: ',
  'office.ai.edit.rewrite': 'Rewrite',
  'office.ai.edit.polish': 'Polish',
  'office.ai.edit.expand': 'Expand',
  'office.ai.edit.condense': 'Condense',
};
