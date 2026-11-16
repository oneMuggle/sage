// P0/P1 (2026-11-04): 附件处理状态字典。
// 独立分域 —— chatAndSider 已接近 800 行架构棘轮，新增键放这里避免继续膨胀。
export const zhAttachmentStatus = {
  // 附件处理状态（attachments_processed 事件回写气泡）
  'chat.attachment_status.summary': '已读取 {ok} 个文件 · 共 {chars} 字符',
  'chat.attachment_status.ok': '已读取',
  'chat.attachment_status.skipped': '已跳过',
  'chat.attachment_status.error': '读取失败',
  'chat.attachment_status.truncated': '内容过长，已截断',
  'chat.attachment_status.rag': '按相关度检索注入',
  // 2026-11-15: PDF 页码 / 插图计数（附件卡片 tooltip / 汇总行）
  'chat.attachment_status.pages': '{n} 页',
  'chat.attachment_status.figures': '{n} 图',
  'chat.attachment_status.preview_close': '关闭',
  'chat.attachment_status.preview_failed': 'PDF 预览失败',
  'chat.attachment_status.preview_loading': '正在加载 PDF…',
  'chat.attachment_status.open_pdf': '查看 PDF 原文',
  'chat.attachment_status.reason.not_document': '文件类型未被识别，请重新上传',
  'chat.attachment_status.reason.not_utf8': '文件不是有效的 UTF-8 文本',
  'chat.attachment_status.reason.empty_text': '文件内容为空',
  'chat.attachment_status.reason.load_failed': '附件不存在或读取失败',
  'chat.attachment_status.reason.context_build_failed': '上下文构建失败',
  'chat.attachment_status.reason.extract_failed': '文档解析失败',
  // P2 预检失败原因
  'chat.attachment_status.reason.oversize': '文件超过 25MB 上限',
  'chat.attachment_status.reason.unsupported': '不支持的文件类型',
  'chat.attachment_status.reason.count_exceeded': '最多上传 10 个附件',
  'chat.attachment_status.reason.duplicate': '同名文件已存在',
  'chat.attachment_status.reason.read_failed': '文件读取失败，请重试',
  'chat.attachment_upload_failed': '以下附件预上传失败，发送时将重试：{files}',
} as const;
