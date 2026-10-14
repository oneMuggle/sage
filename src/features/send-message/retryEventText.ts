/**
 * LLM 重试事件文本格式化 — useChat.ts 与 chatStreamRuntime.ts 共用。
 *
 * 2026-10-13: 从 useChat.ts 抽取，避免主路径/重接路径的重试处理逻辑重复。
 */

import type { RetryInfo } from '../../shared/api/types/chatAndEventTypes';

/**
 * 将错误类型编码为中文标签。未知类型直接透传（不掩盖后端新增类型）。
 */
const ERROR_LABELS: Record<string, string> = {
  timeout: '请求超时',
  network_error: '网络错误',
  server_error: '服务端错误',
  rate_limited: '频率限制',
  auth_failed: '认证失败',
  parsing_error: '响应解析失败',
  context_overflow: '上下文溢出',
  unknown: '未知错误',
};

/**
 * 将 RetryInfo 渲染为用户可读的重试状态文本。
 *
 * 格式：`🔄 重试中 (2/3) | 原因: 请求超时 | 等待 2秒`
 *
 * - delay >= 1 秒取整，< 1 秒保留一位小数
 * - 未知 error_type 直接透传（不被 unknown 吞掉）
 */
export function formatRetryEventText(info: RetryInfo): string {
  const reason = ERROR_LABELS[info.error_type] ?? info.error_type;
  const delayText = info.delay >= 1 ? `${Math.round(info.delay)}` : info.delay.toFixed(1);
  return `🔄 重试中 (${info.attempt}/${info.max_attempts}) | 原因: ${reason} | 等待 ${delayText}秒`;
}
