/**
 * UsageStatsSection — 侧边栏使用量统计组件
 *
 * 显示 Token 和 API 使用情况：
 * - 总请求数和 Token 消耗
 * - 缓存命中率
 * - 成本估算
 * - 按模型分布
 *
 * Backend contract: backend/api/usage_routes.py
 * API client: src/shared/api/usageApi.ts
 *
 * Author: Claude
 * Date: 2026-09-26
 */

import { BarChart3, Loader2, Zap } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  fetchUsageSummary,
  type UsageRange,
  type UsageSummary,
} from '../../../shared/api/usageApi';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface UsageStatsSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function UsageStatsSection({ collapsed, onToggleCollapsed }: UsageStatsSectionProps) {
  const { t } = useI18n();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<UsageRange>('today');

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await fetchUsageSummary(range);
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load usage stats');
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  return (
    <SiderSection
      sectionKey="usage-stats"
      label={t('usage.title')}
      icon={BarChart3}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      render={() => (
        <div className="flex flex-col gap-2 px-2 py-1" data-testid="usage-stats-section">
          {loading && (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-4 h-4 animate-spin text-muted" />
            </div>
          )}

          {error && <div className="text-[11px] text-error px-2 py-1 italic">{error}</div>}

          {!loading && !error && summary && (
            <>
              {/* Range Selector */}
              <div className="flex gap-1">
                {(['today', '7d', '30d', 'total'] as UsageRange[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => setRange(r)}
                    className={[
                      'text-[10px] px-2 py-0.5 rounded-radius-sm transition-colors',
                      range === r
                        ? 'bg-primary/10 text-primary font-medium'
                        : 'text-muted hover:bg-bg-hover',
                    ].join(' ')}
                  >
                    {r === 'today' ? '今日' : r === '7d' ? '7天' : r === '30d' ? '30天' : '全部'}
                  </button>
                ))}
              </div>

              {/* Summary Stats */}
              <div className="grid grid-cols-2 gap-2 pt-1">
                <StatCard icon={Zap} label="请求数" value={summary.totals.requests.toString()} />
                <StatCard
                  icon={BarChart3}
                  label="Token"
                  value={formatNumber(
                    summary.totals.prompt_tokens + summary.totals.completion_tokens,
                  )}
                />
              </div>

              {/* Cache Hit Rate */}
              {summary.cache_hit_rate > 0 && (
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[11px] text-muted">缓存命中率</span>
                  <span className="text-[11px] font-medium text-success">
                    {(summary.cache_hit_rate * 100).toFixed(1)}%
                  </span>
                </div>
              )}

              {/* Cost Estimate */}
              {summary.totals.estimated_cost_usd !== null && (
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[11px] text-muted">估算成本</span>
                  <span className="text-[11px] font-medium text-text">
                    ${summary.totals.estimated_cost_usd.toFixed(4)}
                  </span>
                </div>
              )}

              {/* Top Models */}
              {summary.by_model.length > 0 && (
                <div className="pt-2 border-t border-border/50">
                  <div className="text-[10px] text-muted font-medium mb-1">按模型分布</div>
                  <ul className="flex flex-col gap-0.5">
                    {summary.by_model.slice(0, 3).map((bucket) => (
                      <li
                        key={bucket.model}
                        className="flex items-center justify-between text-[10px]"
                      >
                        <span className="text-text truncate flex-1">{bucket.model}</span>
                        <span className="text-muted flex-shrink-0 ml-2">
                          {formatNumber(bucket.prompt_tokens + bucket.completion_tokens)} tokens
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    />
  );
}

/** Stat card component */
function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 p-2 rounded-radius-sm bg-bg-hover/50">
      <div className="flex items-center gap-1">
        <Icon className="w-3 h-3 text-muted" />
        <span className="text-[10px] text-muted">{label}</span>
      </div>
      <span className="text-xs font-medium text-text">{value}</span>
    </div>
  );
}

/** Format large numbers with K/M suffix */
function formatNumber(num: number): string {
  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1)}M`;
  }
  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(1)}K`;
  }
  return num.toString();
}
