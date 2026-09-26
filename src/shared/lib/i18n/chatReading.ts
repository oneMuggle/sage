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
  // C1 生成速度统计
  'chat.stats_rate': '{rate} tok/s',
  'chat.stats_first_token': '首字 {time}',
  'chat.stats_duration': '耗时 {time}',
  'chat.stats_tokens': '{count} tokens',
  'chat.stats_detail_input': '输入：{count} tokens',
  'chat.stats_detail_output': '输出：{count} tokens',
  'chat.stats_detail_first_token': '首字延迟：{time}',
  'chat.stats_detail_duration': '总耗时：{time}',
  'chat.stats_detail_rate': '生成速度：{rate} tokens/秒',
  // C2 回答版本切换
  'chat.version_label': '回答版本 {current}/{total}',
  'chat.version_prev': '上一个版本',
  'chat.version_next': '下一个版本',
  'chat.version_switch_failed': '切换回答版本失败：{message}',
  // C3 端点离线提示
  'endpoint.offline_network': '无法连接模型端点 {host}，请检查网络或代理设置',
  'endpoint.offline_timeout': '模型端点 {host} 响应超时',
  'endpoint.offline_server': '模型端点 {host} 暂时不可用（HTTP {status}）',
  'endpoint.offline_model': '（模型 {model}）',
  'endpoint.browser_offline': '网络已断开，云端模型暂时不可用；恢复联网后会自动重新检测',
  'endpoint.recheck': '重新检测',
  'endpoint.rechecking': '检测中…',
  'endpoint.recheck_failed': '仍无法连接：{message}',
  'endpoint.recovered': '模型端点已恢复连接',
  'endpoint.open_settings': '端点设置',
  'endpoint.dismiss': '关闭提示',
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
  'chat.stats_rate': '{rate} tok/s',
  'chat.stats_first_token': 'first token {time}',
  'chat.stats_duration': '{time} total',
  'chat.stats_tokens': '{count} tokens',
  'chat.stats_detail_input': 'Input: {count} tokens',
  'chat.stats_detail_output': 'Output: {count} tokens',
  'chat.stats_detail_first_token': 'Time to first token: {time}',
  'chat.stats_detail_duration': 'Total time: {time}',
  'chat.stats_detail_rate': 'Generation speed: {rate} tokens/s',
  'chat.version_label': 'Answer {current} of {total}',
  'chat.version_prev': 'Previous answer',
  'chat.version_next': 'Next answer',
  'chat.version_switch_failed': 'Failed to switch answers: {message}',
  'endpoint.offline_network':
    'Cannot reach the model endpoint {host}. Check your network or proxy settings.',
  'endpoint.offline_timeout': 'The model endpoint {host} timed out.',
  'endpoint.offline_server': 'The model endpoint {host} is unavailable (HTTP {status}).',
  'endpoint.offline_model': ' (model {model})',
  'endpoint.browser_offline':
    'You are offline, so cloud models are unavailable. Sage will re-check once you are back online.',
  'endpoint.recheck': 'Re-check',
  'endpoint.rechecking': 'Checking…',
  'endpoint.recheck_failed': 'Still unreachable: {message}',
  'endpoint.recovered': 'The model endpoint is reachable again.',
  'endpoint.open_settings': 'Endpoint settings',
  'endpoint.dismiss': 'Dismiss',
};
