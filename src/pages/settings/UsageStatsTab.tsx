/**
 * 使用统计 Tab — ZCode 启发新增。
 *
 * 展示 token 消耗趋势(近 7 天 SVG 面积图)、按模型分布(水平条形图)、
 * 汇总卡片(请求数/输入/输出/缓存命中率/成本估算)和 CSV 导出。
 *
 * 数据来源: src/shared/api/usageApi.ts (invoke 通道, 无额外依赖)。
 */
import { Download, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  fetchUsageCsvExport,
  fetchUsageSummary,
  fetchUsageTrend,
  type UsageRange,
  type UsageSummary,
  type UsageTrend,
} from '../../shared/api/usageApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Card } from '../../shared/ui';
import { UsageRequestsTable } from '../../widgets/settings/UsageRequestsTable';
import { monotoneAreaPath } from '../../widgets/settings/chartUtils';

const RANGE_OPTIONS: { value: UsageRange; labelKey: TranslationKey }[] = [
  { value: 'today', labelKey: 'settings.usage.range.today' },
  { value: '7d', labelKey: 'settings.usage.range.7d' },
  { value: '30d', labelKey: 'settings.usage.range.30d' },
  { value: 'total', labelKey: 'settings.usage.range.total' },
];

const COLORS = {
  prompt: '#6366f1', // indigo
  completion: '#10b981', // emerald
  cached: '#f59e0b', // amber
};

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(usd: number | null): string {
  if (usd == null) return '—';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export function UsageStatsTab() {
  const { t } = useI18n();
  const [range, setRange] = useState<UsageRange>('7d');
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [trend, setTrend] = useState<UsageTrend | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const loadData = useCallback(async (r: UsageRange) => {
    setLoading(true);
    setError(null);
    try {
      const [s, t] = await Promise.all([fetchUsageSummary(r), fetchUsageTrend({ range: r })]);
      setSummary(s);
      setTrend(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData(range);
  }, [range, loadData]);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const csv = await fetchUsageCsvExport({ range });
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `usage-${range}-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    } finally {
      setExporting(false);
    }
  }, [range]);

  if (loading && !summary) {
    return (
      <div className="flex items-center justify-center h-64 text-text-muted">
        {t('settings.usage.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        {t('settings.usage.load_failed').replace('{error}', error)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-text">{t('settings.usage.title')}</h3>
        <div className="flex items-center gap-2">
          {/* Range selector */}
          <div className="flex rounded-md border border-border overflow-hidden">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setRange(opt.value)}
                className={`px-3 py-1 text-xs transition-colors ${
                  range === opt.value
                    ? 'bg-primary text-text-inverse'
                    : 'text-text-muted hover:bg-bg-hover'
                }`}
              >
                {t(opt.labelKey)}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-1 px-3 py-1 text-xs border border-border rounded-md text-text-muted hover:bg-bg-hover transition-colors disabled:opacity-50"
          >
            <Download className="w-3 h-3" />
            {exporting ? t('settings.usage.exporting') : 'CSV'}
          </button>
        </div>
      </div>

      {/* Summary cards */}
      {summary && <SummaryCards summary={summary} />}

      {/* Trend chart */}
      {trend && trend.series.length > 0 && <TrendChart trend={trend} />}

      {/* Model breakdown */}
      {summary && summary.by_model.length > 0 && <ModelBreakdown byModel={summary.by_model} />}

      {/* 请求明细（原「通用」tab 的 UsagePanel 二级面板，2026-10-28 迁入） */}
      <section className="space-y-3">
        <h4 className="text-sm font-semibold text-text">{t('settings.usage.requests_detail')}</h4>
        <UsageRequestsTable />
      </section>
    </div>
  );
}

// ---- Summary Cards ----
function SummaryCards({ summary }: { summary: UsageSummary }) {
  const { t } = useI18n();
  const bucket = summary.totals;
  const cards: { labelKey: TranslationKey; value: string; color?: string; subtitle?: string }[] = [
    { labelKey: 'settings.usage.card.total_requests', value: formatNumber(bucket.requests) },
    {
      labelKey: 'settings.usage.card.prompt_tokens',
      value: formatNumber(bucket.prompt_tokens),
      color: COLORS.prompt,
    },
    {
      labelKey: 'settings.usage.card.completion_tokens',
      value: formatNumber(bucket.completion_tokens),
      color: COLORS.completion,
    },
    {
      labelKey: 'settings.usage.card.cache_hit_rate',
      value: formatPct(summary.cache_hit_rate),
      color: COLORS.cached,
    },
    {
      labelKey: 'settings.usage.card.est_cost',
      value: formatCost(bucket.estimated_cost_usd),
      subtitle: summary.has_partial_estimates
        ? t('settings.usage.card.partial_estimate')
        : undefined,
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {cards.map((c) => (
        <Card key={c.labelKey} className="p-3">
          <div className="text-xs text-text-muted mb-1">{t(c.labelKey)}</div>
          <div
            className="text-xl font-semibold text-text"
            style={c.color ? { color: c.color } : undefined}
          >
            {c.value}
          </div>
          {c.subtitle && <div className="text-ui-xs text-text-muted mt-0.5">{c.subtitle}</div>}
        </Card>
      ))}
    </div>
  );
}

// ---- Trend Chart (pure SVG area chart) ----
function TrendChart({ trend }: { trend: UsageTrend }) {
  const { t } = useI18n();
  const { series } = trend;
  const maxTokens = useMemo(
    () => Math.max(1, ...series.map((p) => p.prompt_tokens + p.completion_tokens)),
    [series],
  );

  const width = 600;
  const height = 180;
  const padX = 40;
  const padY = 20;
  const chartW = width - padX * 2;
  const chartH = height - padY * 2;

  const xStep = series.length > 1 ? chartW / (series.length - 1) : chartW;
  const baselineY = padY + chartH;

  const makeArea = (getter: (p: (typeof series)[0]) => number) => {
    const points = series.map((p, i) => ({
      x: padX + i * xStep,
      y: padY + chartH - (getter(p) / maxTokens) * chartH,
    }));
    return monotoneAreaPath(points, baselineY);
  };

  const promptArea = makeArea((p) => p.prompt_tokens);
  const completionArea = makeArea((p) => p.completion_tokens);

  // Y-axis labels
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((frac) => ({
    y: padY + chartH - frac * chartH,
    label: formatNumber(Math.round(frac * maxTokens)),
  }));

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-4 h-4 text-primary" />
        <h4 className="text-sm font-medium text-text">{t('settings.usage.trend_title')}</h4>
        <div className="ml-auto flex items-center gap-3 text-ui-xs">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: COLORS.prompt }} />
            {t('settings.usage.legend_input')}
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: COLORS.completion }} />
            {t('settings.usage.legend_output')}
          </span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto">
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <g key={tick.label}>
            <line
              x1={padX}
              y1={tick.y}
              x2={width - padX}
              y2={tick.y}
              stroke="currentColor"
              className="text-border"
              strokeWidth={0.5}
            />
            <text
              x={padX - 4}
              y={tick.y + 3}
              textAnchor="end"
              className="fill-text-muted"
              fontSize={8}
            >
              {tick.label}
            </text>
          </g>
        ))}
        {/* Areas */}
        <path d={promptArea} fill={COLORS.prompt} opacity={0.3} />
        <path d={completionArea} fill={COLORS.completion} opacity={0.3} />
        {/* X-axis labels (first / middle / last) */}
        {series.length > 0 && (
          <>
            {[0, Math.floor(series.length / 2), series.length - 1].map((idx) => {
              const x = padX + idx * xStep;
              const date = new Date(series[idx].ts);
              const label =
                trend.bucket === 'hour'
                  ? `${date.getHours()}:00`
                  : `${date.getMonth() + 1}/${date.getDate()}`;
              return (
                <text
                  key={idx}
                  x={x}
                  y={height - 2}
                  textAnchor={idx === 0 ? 'start' : idx === series.length - 1 ? 'end' : 'middle'}
                  className="fill-text-muted"
                  fontSize={8}
                >
                  {label}
                </text>
              );
            })}
          </>
        )}
      </svg>
    </Card>
  );
}

// ---- Model Breakdown (horizontal bar chart) ----
function ModelBreakdown({
  byModel,
}: {
  byModel: {
    model: string;
    requests: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost_usd: number | null;
  }[];
}) {
  const { t } = useI18n();
  const sorted = useMemo(
    () =>
      [...byModel].sort(
        (a, b) => b.prompt_tokens + b.completion_tokens - (a.prompt_tokens + a.completion_tokens),
      ),
    [byModel],
  );
  const maxTokens = Math.max(1, ...sorted.map((m) => m.prompt_tokens + m.completion_tokens));

  return (
    <Card className="p-4">
      <h4 className="text-sm font-medium text-text mb-3">{t('settings.usage.by_model')}</h4>
      <div className="space-y-2">
        {sorted.map((m) => {
          const total = m.prompt_tokens + m.completion_tokens;
          const promptPct = (m.prompt_tokens / total) * 100;
          const widthPct = (total / maxTokens) * 100;
          return (
            <div key={m.model}>
              <div className="flex items-center justify-between text-xs mb-0.5">
                <span className="text-text truncate max-w-[60%]" title={m.model}>
                  {m.model}
                </span>
                <span className="text-text-muted flex-shrink-0">
                  {formatNumber(total)} tokens · {m.requests} {t('settings.usage.times_suffix')}
                  {m.estimated_cost_usd != null && ` · ${formatCost(m.estimated_cost_usd)}`}
                </span>
              </div>
              <div className="h-2 rounded-full bg-bg-muted overflow-hidden">
                <div className="h-full flex" style={{ width: `${widthPct}%` }}>
                  <div
                    className="h-full"
                    style={{ width: `${promptPct}%`, background: COLORS.prompt }}
                  />
                  <div
                    className="h-full"
                    style={{ width: `${100 - promptPct}%`, background: COLORS.completion }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditUsageStatsTabGovernance(
  state: {
    totalTokens?: number;
    sessionCount?: number;
    timeRangeDays?: number;
  } = {},
): {
  module: 'src/pages/settings/UsageStatsTab.tsx';
  phase: 'P143';
  totalTokens: number;
  sessionCount: number;
  timeRangeDays: number;
  healthy: boolean;
} {
  const totalTokens =
    typeof state.totalTokens === 'number' && Number.isFinite(state.totalTokens)
      ? Math.max(0, Math.trunc(state.totalTokens))
      : 0;
  const sessionCount =
    typeof state.sessionCount === 'number' && Number.isFinite(state.sessionCount)
      ? Math.max(0, Math.trunc(state.sessionCount))
      : 0;
  const timeRangeDays =
    typeof state.timeRangeDays === 'number' && Number.isFinite(state.timeRangeDays)
      ? Math.max(1, Math.trunc(state.timeRangeDays))
      : 30;
  return {
    module: 'src/pages/settings/UsageStatsTab.tsx',
    phase: 'P143',
    totalTokens,
    sessionCount,
    timeRangeDays,
    healthy: totalTokens >= 0 && sessionCount >= 0 && timeRangeDays >= 1,
  };
}
