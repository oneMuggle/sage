/**
 * 聊天附件格式常量 —— 独立于 useFileUpload hook，避免测试 mock hook 时
 * 常量随模块一起被替换（InputCard 等纯展示组件只依赖这里的常量）。
 *
 * 2026-11-15: 从 useFileUpload.ts 抽出；useFileUpload 继续再导出，保持既有
 * import 路径兼容。新增格式时同时更新这里与后端
 * `chat_attachment_routes.EXTRACTABLE_DOC_EXTENSIONS`。
 */

/** r75/r76: 聊天文档附件支持的扩展名（Chat.tsx 上传白名单与 ChatInput
 * 提示条件共用，避免两处口径漂移）。
 * 2026-10-13: 扩展覆盖常见编程语言、配置、数据格式，与后端
 * ALLOWED_TEXT_EXTENSIONS + EXTRACTABLE_DOC_EXTENSIONS 同口径。 */
export const CHAT_DOCUMENT_EXTENSIONS = new Set([
  // 基础文本
  'txt',
  'md',
  'csv',
  // 编程语言
  'py',
  'js',
  'ts',
  'jsx',
  'tsx',
  'java',
  'go',
  'rs',
  'rb',
  'php',
  'c',
  'cpp',
  'h',
  'hpp',
  'cs',
  'swift',
  'kt',
  'scala',
  'r',
  // 前端
  'html',
  'css',
  'scss',
  'less',
  'vue',
  'svelte',
  // 数据/配置
  'json',
  'yaml',
  'yml',
  'xml',
  'toml',
  'ini',
  'cfg',
  'conf',
  // 脚本/构建
  'sh',
  'bash',
  'bat',
  'ps1',
  'sql',
  'makefile',
  'cmake',
  'gradle',
  // 特殊命名
  'dockerfile',
  'gitignore',
  'properties',
  // 日志
  'log',
  // 二进制文档（需后端解析）
  'pdf',
  'docx',
  'xlsx',
  'pptx',
]);

/** r78: 文件选择器 accept 提示 —— 由 CHAT_DOCUMENT_EXTENSIONS 派生，
 * 保证对话框过滤与拖放/粘贴预检永远同口径。
 * 注：dockerfile/gitignore/properties 是特殊文件名，会被派生成
 * `.dockerfile` 等伪扩展名，浏览器选择器不会匹配；拖放/粘贴仍按扩展名放行。 */
export const CHAT_DOCUMENT_ACCEPT = Array.from(CHAT_DOCUMENT_EXTENSIONS)
  .sort()
  .map((ext) => `.${ext}`)
  .join(',');

/** 与后端 chat_stream_support._ALLOWED_IMAGE_MIME_PREFIXES 同口径。
 * 仅支持主流多模态接口能直接接收的四种格式；BMP/SVG/HEIC 在预检阶段拒绝。 */
export const CHAT_IMAGE_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
]);

export const CHAT_IMAGE_ACCEPT = Array.from(CHAT_IMAGE_MIME_TYPES).join(',');

// P2 (2026-11-04): 前端预检硬限制 —— 与后端 `MAX_ATTACHMENT_SIZE` / 注入循环
// `[:10]` 同口径；在 selection 阶段就拒绝，而不是上传后才 toast。
export const MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024; // 25 MB
export const MAX_ATTACHMENT_COUNT = 10;

/** 2026-11-24: 无扩展名但允许上传的文件名（小写精确匹配）。
 * 与后端 `chat_attachment_routes.NO_EXT_FILENAMES` 同口径。
 * 用于 `preflightAttachment` 显式处理无点文件名。 */
export const CHAT_NO_EXT_FILENAMES = new Set(['makefile', 'dockerfile']);
