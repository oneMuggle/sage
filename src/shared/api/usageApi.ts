/**
 * Usage/cost API client (M6 生态扩展)。
 *
 * 后端: GET /api/v1/usage (backend/api/usage_routes.py), 内存态 tracker。
 * 字段保持后端 snake_case 线格式 (invoke 不做响应转换)。
 *
 * L8 PR-A (2026-09-09): 新增 cache_read_tokens / cache_creation_tokens
 * 拆分字段 + 派生 cache_hit_rate; sessionUsage 同样扩展。
 * L8 PR-B (2026-09-09): range 扩到 today|7d|30d|total; 新增 fetchUsageRequests。
 */
import { invoke } from './desktopInvoke';

export interface UsageBucket {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  /** L4: 历史合并字段 (read+creation 总和), 保留兼容 */
  cached_tokens: number;
  /** L8 PR-A: 从缓存读取的 token (成本极低) */
  cache_read_tokens: number;
  /** L8 PR-A: 创建缓存条目的 token (成本略高) */
  cache_creation_tokens: number;
  estimated_cost_usd: number | null;
}

export interface UsageModelBucket extends UsageBucket {
  model: string;
}

export interface UsageSummary {
  totals: UsageBucket;
  by_model: UsageModelBucket[];
  today: UsageBucket;
  /** L8 PR-A: cache_read / (prompt + cache_creation) 派生命中率 (0~1) */
  cache_hit_rate: number;
  /** L8 PR-A/PR-B: 当前面板时间范围 (today | 7d | 30d | total) */
  range: 'today' | '7d' | '30d' | 'total';
}

/** L8 PR-B (2026-09-09): 时间范围联合类型 */
export type UsageRange = 'today' | '7d' | '30d' | 'total';

export async function fetchUsageSummary(range?: UsageRange): Promise<UsageSummary> {
  return invoke<UsageSummary>('usage_summary', range ? { range } : undefined);
}

/** L8 PR-B (2026-09-09): 单次请求详情 (usage_events 行) */
export interface UsageRequestRow {
  id: string;
  session_id: string | null;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  estimated_cost_usd: number | null;
  created_at_ms: number;
  created_at_iso: string;
}

export interface UsageRequestsPage {
  items: UsageRequestRow[];
  total: number;
  limit: number;
  offset: number;
  error?: string;
}

export async function fetchUsageRequests(
  params: { limit?: number; offset?: number; sessionId?: string } = {},
): Promise<UsageRequestsPage> {
  return invoke<UsageRequestsPage>('usage_list_requests', params);
}

/** U14 (批次 C): 某会话的持久化用量聚合 (usage_events 表, 重启不丢) */
export interface SessionUsage {
  session_id: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  /** L4: 累计缓存命中 token (历史字段, 兼容) */
  cached_tokens: number;
  /** L8 PR-A: 该会话累计 cache_read_tokens */
  cache_read_tokens: number;
  /** L8 PR-A: 该会话累计 cache_creation_tokens */
  cache_creation_tokens: number;
  /** L8 PR-A: 该会话命中率派生 (0~1) */
  cache_hit_rate: number;
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
