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

export interface GenerationStatsAuditSnapshot {
  hasStats: boolean;
  outputTokens: number;
  inputTokens: number;
  latencyMs: number;
  firstTokenMs: number | null;
  rateTokensPerSec: number | null;
  formattedRate: string | null;
  formattedDuration: string | null;
  signature: string;
}

export function buildGenerationStatsAuditSnapshot(
  stats?: GenerationStats | null,
): GenerationStatsAuditSnapshot {
  const hasStats = Boolean(stats && typeof stats === 'object');
  const outputTokens =
    typeof stats?.output_tokens === 'number' && stats.output_tokens > 0
      ? Math.round(stats.output_tokens)
      : 0;
  const inputTokens =
    typeof stats?.input_tokens === 'number' && stats.input_tokens > 0
      ? Math.round(stats.input_tokens)
      : 0;
  const latencyMs =
    typeof stats?.latency_ms === 'number' && stats.latency_ms > 0
      ? Math.round(stats.latency_ms)
      : 0;
  const firstTokenMs =
    typeof stats?.first_token_ms === 'number' && stats.first_token_ms >= 0
      ? Math.round(stats.first_token_ms)
      : null;
  const rawRate = tokensPerSecond(stats);
  const rateTokensPerSec = rawRate !== null ? Number(rawRate.toFixed(2)) : null;
  const formattedRate = rawRate !== null ? formatRate(rawRate) : null;
  const formattedDuration = latencyMs > 0 ? formatDuration(latencyMs) : null;
  const signature = `${hasStats ? 1 : 0}|${outputTokens}|${inputTokens}|${latencyMs}|${firstTokenMs ?? -1}|${formattedRate ?? '-'}|${formattedDuration ?? '-'}`;
  return {
    hasStats,
    outputTokens,
    inputTokens,
    latencyMs,
    firstTokenMs,
    rateTokensPerSec,
    formattedRate,
    formattedDuration,
    signature,
  };
}

export function buildGenerationStatsAuditJson(stats?: GenerationStats | null): string {
  return JSON.stringify(buildGenerationStatsAuditSnapshot(stats), null, 2);
}
