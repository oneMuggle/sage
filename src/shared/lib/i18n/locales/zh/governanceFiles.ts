/** 项目工作台 · 文件引用词典 — 中文（默认）。 */
export const zhGovernanceFiles = {
  'governance.files.subtitle': '文件引用让 AI 以只读方式访问项目之外的资源。',
  'governance.files.scan.idle': '重新扫描',
  'governance.files.scan.busy': '扫描中...',
  'governance.files.create.title': '新增引用',
  'governance.files.create.relPath': '项目相对路径 *',
  'governance.files.create.targetPath': '目标绝对路径 *',
  'governance.files.create.alias': '别名',
  'governance.files.create.kind': '类型',
  'governance.files.create.kind.directory': '文件夹',
  'governance.files.create.kind.file': '文件',
  'governance.files.create.kind.symlink': '符号链接',
  'governance.files.create.submitting': '添加中...',
  'governance.files.create.submit': '新增引用',
  'governance.files.list.loading': '正在加载引用...',
  'governance.files.list.empty':
    '暂无引用。可在上方新增，或点击「重新扫描」识别项目中的符号链接。',
  'governance.files.row.created': '创建于',
  'governance.files.confirm.title': '删除引用？',
  'governance.files.confirm.messageTail': '将被移除，源文件不会被删除。',
  'governance.files.confirm.delete': '删除',
} as const;

export type GovernanceFilesTranslationKey = keyof typeof zhGovernanceFiles;
