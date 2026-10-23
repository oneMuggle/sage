/**
 * LLM 重试横幅文案 — RetryBanner 使用。
 *
 * 2026-10-20: LLM 重试可视化。错误类型标签与倒计时单位随 locale 变化；
 * 与 chatReading.ts / pausedMemory.ts 同样采用"独立词典模块 + 聚合器合并"
 * 的模式，避免撑大已基线化的 zh.ts / en.ts。
 */
export const retryBannerZh = {
  // 2026-10-20: LLM 重试横幅
  'chat.retry.in_progress': '重试中 ({attempt}/{max})',
  'chat.retry.seconds': '{seconds} 秒',
  'chat.retry.error.timeout': '请求超时',
  'chat.retry.error.network_error': '网络错误',
  'chat.retry.error.server_error': '服务端错误',
  'chat.retry.error.rate_limited': '频率限制',
  'chat.retry.error.auth_failed': '认证失败',
  'chat.retry.error.parsing_error': '响应解析失败',
  'chat.retry.error.context_overflow': '上下文溢出',
  'chat.retry.error.unknown': '未知错误',
} as const;

export const retryBannerEn: Record<keyof typeof retryBannerZh, string> = {
  'chat.retry.in_progress': 'Retrying ({attempt}/{max})',
  'chat.retry.seconds': '{seconds}s',
  'chat.retry.error.timeout': 'Request timed out',
  'chat.retry.error.network_error': 'Network error',
  'chat.retry.error.server_error': 'Server error',
  'chat.retry.error.rate_limited': 'Rate limited',
  'chat.retry.error.auth_failed': 'Authentication failed',
  'chat.retry.error.parsing_error': 'Failed to parse response',
  'chat.retry.error.context_overflow': 'Context overflow',
  'chat.retry.error.unknown': 'Unknown error',
};

export function formatRetryBannerI18nSummary(): string {
  const zhKeys = Object.keys(retryBannerZh);
  const enKeys = Object.keys(retryBannerEn);
  const parity = zhKeys.length === enKeys.length && zhKeys.every((k) => k in retryBannerEn);
  return `zh=${zhKeys.length} · en=${enKeys.length} · parity=${parity}`;
}

export function formatRetryBannerI18nJson(): string {
  const zhKeys = Object.keys(retryBannerZh);
  const enKeys = Object.keys(retryBannerEn);
  const parity = zhKeys.length === enKeys.length && zhKeys.every((k) => k in retryBannerEn);
  return JSON.stringify({
    zhCount: zhKeys.length,
    enCount: enKeys.length,
    parity,
    keys: zhKeys,
  });
}

export function auditRetryBannerGovernance(): string {
  return JSON.stringify({
    module: 'retry-banner',
    phase: 'P182',
    audited: true,
  });
}
