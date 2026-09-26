/**
 * 对话阅读体验 C1（docs/mcp-chat-reading-nav-optimization.md §10.6）：生成速度统计的
 * 计算与格式化。
 *
 * 速度 = 输出 tokens ÷（总耗时 − 首字延迟）：首字之前是排队和预填充，不算生成；
 * 没有首字延迟（非流式请求）时按总耗时计算。上游没有返回用量时不给速度。
 */
import type { GenerationStats } from '../../shared/api/types';

export function tokensPerSecond(stats: GenerationStats | null | undefined): number | null {
  const outputTokens = stats?.output_tokens;
  const latencyMs = stats?.latency_ms;
  if (!outputTokens || outputTokens <= 0 || !latencyMs || latencyMs <= 0) return null;
  const firstTokenMs = stats?.first_token_ms;
  const generatingMs =
    firstTokenMs != null && firstTokenMs >= 0 && firstTokenMs < latencyMs
      ? latencyMs - firstTokenMs
      : latencyMs;
  return (outputTokens * 1000) / generatingMs;
}

/** 毫秒 → 0.82s / 12.4s / 2m05s */
export function formatDuration(ms: number): string {
  const seconds = Math.max(0, ms) / 1000;
  if (seconds < 10) return `${seconds.toFixed(2)}s`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}m${String(total % 60).padStart(2, '0')}s`;
}

export function formatRate(rate: number): string {
  return rate >= 100 ? String(Math.round(rate)) : rate.toFixed(1);
}

export function formatCount(count: number, locale: string): string {
  return Math.round(count).toLocaleString(locale === 'en' ? 'en-US' : 'zh-CN');
}
