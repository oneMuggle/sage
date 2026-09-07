/**
 * Usage/cost API client (M6 生态扩展)。
 *
 * 后端: GET /api/v1/usage (backend/api/usage_routes.py), 内存态 tracker。
 * 字段保持后端 snake_case 线格式 (invoke 不做响应转换)。
 */
import { invoke } from './desktopInvoke';

export interface UsageBucket {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number | null;
}

export interface UsageModelBucket extends UsageBucket {
  model: string;
}

export interface UsageSummary {
  totals: UsageBucket;
  by_model: UsageModelBucket[];
  today: UsageBucket;
}

export async function fetchUsageSummary(): Promise<UsageSummary> {
  return invoke<UsageSummary>('usage_summary');
}

/** U14 (批次 C): 某会话的持久化用量聚合 (usage_events 表, 重启不丢) */
export interface SessionUsage {
  session_id: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  /** L4: 累计缓存命中 token */
  cached_tokens: number;
  // U17 (round4): 最近一次请求的模型与 prompt 用量——ContextMeter 数据源。
  // 上一轮 prompt_tokens 即当前上下文占用的最佳代理;无记录时为 null。
  last_model: string | null;
  last_prompt_tokens: number | null;
  last_cached_tokens: number | null;
  last_at_ms: number | null;
}

export async function fetchSessionUsage(sessionId: string): Promise<SessionUsage> {
  return invoke<SessionUsage>('usage_get_session', { sessionId });
}
