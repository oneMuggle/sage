/**
 * 对话阅读体验文案（docs/mcp-chat-reading-nav-optimization.md §10）。
 *
 * 独立成模块，由 index.tsx 合并进 zh / en 词典：zh.ts / en.ts 已在架构基线上且没有
 * 余量（architecture-baseline.json），新文案放这里不让基线文件继续增长。
 */
export const chatReadingZh = {
  // B1 消息朗读
  'chat.read_aloud': '朗读',
  'chat.read_aloud_stop': '停止朗读',
  'chat.read_aloud_code_omitted': '此处代码已略过。',
  // B2 截断提示 + 继续生成
  'chat.truncated_notice': '回答达到长度上限，已被截断',
  'chat.continue_generating': '继续生成',
  'chat.continue_prompt': '请从上次中断的地方继续，不要重复已经输出的内容。',
  // B4 会话内查找
  'chat.find_label': '会话内查找',
  'chat.find_placeholder': '在当前会话中查找',
  'chat.find_hint': 'Enter 更早 · Shift+Enter 更新 · Esc 关闭',
  'chat.find_no_results': '无结果',
  'chat.find_prev': '上一处（更早）',
  'chat.find_next': '下一处（更新）',
  'chat.find_close': '关闭查找',
} as const;

export const chatReadingEn: Record<keyof typeof chatReadingZh, string> = {
  'chat.read_aloud': 'Read aloud',
  'chat.read_aloud_stop': 'Stop reading',
  'chat.read_aloud_code_omitted': 'Code omitted.',
  'chat.truncated_notice': 'The reply hit the length limit and was cut off',
  'chat.continue_generating': 'Continue generating',
  'chat.continue_prompt':
    'Please continue exactly where you left off, without repeating what you already wrote.',
  'chat.find_label': 'Find in conversation',
  'chat.find_placeholder': 'Find in this conversation',
  'chat.find_hint': 'Enter older · Shift+Enter newer · Esc close',
  'chat.find_no_results': 'No results',
  'chat.find_prev': 'Previous (older)',
  'chat.find_next': 'Next (newer)',
  'chat.find_close': 'Close find',
};
