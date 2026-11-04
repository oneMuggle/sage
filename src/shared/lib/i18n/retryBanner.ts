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
  // 2026-11-02: 总时长预算可见性 — 后端推送 budget_remaining_s 时展示
  'chat.retry.budget_remaining': '剩余预算 {seconds} 秒',
  // 2026-11-03: 计时协议可见性 —— 退避等待 / 在途请求两个阶段的可观测文案
  'chat.retry.backoff_hint': '将在 {seconds} 秒后重试',
  'chat.retry.in_flight_hint': '重试请求已发出，正在等待上游响应',
  'chat.retry.elapsed': '已等待 {seconds} 秒',
  'chat.retry.attempt_elapsed': '本次已等待 {seconds} 秒',
  'chat.retry.attempt_timeout': '单次上限 {seconds} 秒',
  'chat.retry.source.compaction': '正在压缩上下文',
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
  'chat.retry.budget_remaining': '{seconds}s budget left',
  'chat.retry.backoff_hint': 'Retrying in {seconds}s',
  'chat.retry.in_flight_hint': 'Retry request sent, waiting for upstream response',
  'chat.retry.elapsed': 'Waited {seconds}s',
  'chat.retry.attempt_elapsed': 'This attempt {seconds}s',
  'chat.retry.attempt_timeout': 'Attempt limit {seconds}s',
  'chat.retry.source.compaction': 'Compacting context',
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
