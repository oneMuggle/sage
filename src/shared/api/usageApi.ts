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
