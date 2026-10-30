/**
 * 用量趋势图 — 堆叠柱 + 分时段 hover 详情卡。
 *
 * 设计参考主流 AI 控制台（OpenAI Usage / Anthropic Console / Cursor Usage）:
 * - 连续时间轴: today 24 个小时槽, 7d/30d/total 固定日槽（后端补零保证）；
 * - 堆叠柱: 输入 token（靛蓝）在下、输出 token（翠绿）在上；
 * - 成本虚线沿用右轴, 悬停任意时段显示详情卡；
 * - 详情卡: 请求数 / 输入 / 输出 / 总 token / 缓存读取 / 缓存创建 /
 *   命中率 / 成本估算, 未定价请求以徽标提示；
 * - 键盘可达: ←/→ 切换时段, Home/End 跳首尾, Esc 关闭；
 * - 触摸: 点击时段等同 hover。
 *
 * 保持自绘 SVG（不引入图表库），与既有 Tailwind 字号/颜色体系一致。
 */
import { useMemo, useState } from 'react';

import type { UsageTrend, UsageTrendPoint } from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';
import { Card } from '../../shared/ui';

import { monotonePath } from './chartUtils';

const SVG_W = 600;
const SVG_H = 200;
const PAD_L = 44;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 30;

const COLOR_INPUT = '#6366f1'; // indigo
const COLOR_OUTPUT = '#10b981'; // emerald
const COLOR_COST = '#f59e0b'; // amber

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(usd: number | null | undefined): string {
  if (usd == null) return '—';
  if (usd === 0) return '$0.0000';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatPct(rate: number | null | undefined): string {
  return `${((rate ?? 0) * 100).toFixed(1)}%`;
}

function totalTokens(p: UsageTrendPoint): number {
  return p.total_tokens ?? p.prompt_tokens + p.completion_tokens;
}

function cacheRead(p: UsageTrendPoint): number {
  return p.cache_read_tokens ?? p.cached_tokens ?? 0;
}

function cacheCreation(p: UsageTrendPoint): number {
  return p.cache_creation_tokens ?? 0;
}

function unknownRequests(p: UsageTrendPoint): number {
  return p.unknown_requests ?? 0;
}

/** 把桶起始 ts 格式化为详情卡标题：小时槽 "10/30 14:00–15:00"，日槽 "10/30"。 */
// eslint-disable-next-line react-refresh/only-export-components
export function formatPeriodLabel(ts: string, bucket: 'hour' | 'day'): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  const md = `${pad2(date.getMonth() + 1)}/${pad2(date.getDate())}`;
  if (bucket === 'hour') {
    const h = date.getHours();
    return `${md} ${pad2(h)}:00–${pad2((h + 1) % 24)}:00`;
  }
  return md;
}

function formatTick(ts: string, bucket: 'hour' | 'day', idx: number, total: number): string {
  if (!ts) return '';
  if (bucket === 'hour') {
    const t = ts.indexOf('T');
    if (t < 0) return '';
    return ts.slice(t + 1, t + 6);
  }
  // 日槽不在中间点显示，避免密集重叠
  if (idx !== 0 && idx !== total - 1) return '';
  return ts.length >= 10 ? ts.slice(5, 10) : '';
}

interface UsageTrendChartProps {
  trend: UsageTrend | null;
  loading: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatUsageTrendMarkdown(trend: UsageTrend | null): string {
  const series = trend?.series ?? [];
  const lines = [
    `# 用量趋势 (${trend?.range ?? '—'} · ${trend?.bucket ?? 'day'})`,
    `- 数据点数: ${series.length}`,
  ];
  for (const pt of series) {
    lines.push(
      `- **${pt.ts}**: 请求 ${pt.requests} · 输入 ${pt.prompt_tokens} · 输出 ${pt.completion_tokens} · 缓存命中 ${cacheRead(pt)} / 创建 ${cacheCreation(pt)} · 成本 $${pt.cost_usd.toFixed(4)} · 缓存命中率 ${Math.round((pt.cache_hit_rate ?? 0) * 100)}%`,
    );
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatUsageTrendJson(trend: UsageTrend | null): string {
  const series = trend?.series ?? [];
  return JSON.stringify(
    {
      range: trend?.range ?? null,
      bucket: trend?.bucket ?? 'day',
      count: series.length,
      series,
    },
    null,
    2,
  );
}

export function UsageTrendChart({ trend, loading }: UsageTrendChartProps) {
  const { t } = useI18n();
  const series = useMemo<UsageTrendPoint[]>(() => trend?.series ?? [], [trend?.series]);
  const bucket = trend?.bucket ?? 'day';
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const layout = useMemo(() => {
    const innerW = SVG_W - PAD_L - PAD_R;
    const innerH = SVG_H - PAD_T - PAD_B;
    const slotW = series.length > 0 ? innerW / series.length : innerW;
    const barW = Math.max(1, Math.min(18, slotW * 0.62));
    const maxTotal = Math.max(1, ...series.map((p) => totalTokens(p)));
    const maxCost = Math.max(1e-9, ...series.map((p) => p.cost_usd ?? 0));
    const bars = series.map((p, i) => {
      const promptH = (p.prompt_tokens / maxTotal) * innerH;
      const completionH = (p.completion_tokens / maxTotal) * innerH;
      const x = PAD_L + i * slotW + (slotW - barW) / 2;
      const centerX = PAD_L + i * slotW + slotW / 2;
      const inputY = PAD_T + innerH - promptH;
      const outputY = inputY - completionH;
      const costY = PAD_T + innerH - ((p.cost_usd ?? 0) / maxCost) * innerH;
      return { raw: p, x, centerX, inputY, outputY, promptH, completionH, costY };
    });
    const costPath = monotonePath(bars.map((b) => ({ x: b.centerX, y: b.costY })));
    const ticks = Array.from(new Set([0, Math.floor(series.length / 2), series.length - 1])).filter(
      (i) => i >= 0 && i < series.length,
    );
    return { innerW, innerH, slotW, barW, maxTotal, maxCost, bars, costPath, ticks };
  }, [series]);

  const active = activeIndex !== null && activeIndex < series.length ? series[activeIndex] : null;
  const activeBar = active !== null ? (layout.bars[activeIndex as number] ?? null) : null;
  const activeXPercent = activeBar !== null ? ((activeBar.centerX / SVG_W) * 100).toFixed(2) : '0';
  const alignRight = activeIndex !== null && activeIndex >= series.length - 2;
  const alignLeft = activeIndex !== null && activeIndex <= 1;
  const tooltipAlignClass = alignLeft
    ? 'translate-x-0'
    : alignRight
      ? '-translate-x-full'
      : '-translate-x-1/2';

  const moveActive = (delta: number) => {
    if (series.length === 0) return;
    setActiveIndex((prev) => {
      const base = prev ?? (delta > 0 ? -1 : series.length);
      return Math.min(series.length - 1, Math.max(0, base + delta));
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (series.length === 0) return;
    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault();
        moveActive(-1);
        break;
      case 'ArrowRight':
        event.preventDefault();
        moveActive(1);
        break;
      case 'Home':
        event.preventDefault();
        setActiveIndex(0);
        break;
      case 'End':
        event.preventDefault();
        setActiveIndex(series.length - 1);
        break;
      case 'Escape':
        setActiveIndex(null);
        break;
      default:
        break;
    }
  };

  if (loading) {
    return (
      <div
        className="pt-2 border-t border-border text-xs text-text-muted"
        data-testid="usage-trend-loading"
      >
        {t('settings.usage.trend.loading')}
      </div>
    );
  }

  if (series.length === 0) {
    return (
      <div
        className="pt-2 border-t border-border text-xs text-text-muted"
        data-testid="usage-trend-empty"
      >
        {t('settings.usage.trend.empty')}
      </div>
    );
  }

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-medium text-text">{t('settings.usage.trend.title')}</h4>
        <div className="flex items-center gap-3 text-ui-xs text-text-muted">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: COLOR_INPUT }} />
            {t('settings.usage.legend_input')}
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: COLOR_OUTPUT }} />
            {t('settings.usage.legend_output')}
          </span>
          <span className="flex items-center gap-1" data-testid="usage-trend-legend-cost">
            <span className="w-2 h-2 rounded-full" style={{ background: COLOR_COST }} />
            {t('settings.usage.trend.legendCost')}
          </span>
        </div>
      </div>
      <div
        className="relative outline-none focus-visible:ring-1 focus-visible:ring-primary rounded-radius-sm"
        tabIndex={0}
        role="group"
        aria-label={t('settings.usage.trend.title')}
        data-testid="usage-trend-chart"
        onKeyDown={onKeyDown}
        onFocus={() => {
          if (activeIndex === null && series.length > 0) setActiveIndex(series.length - 1);
        }}
        onBlur={() => setActiveIndex(null)}
      >
        <svg
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          className="w-full h-auto"
          role="img"
          aria-label={t('settings.usage.trend.hint')}
        >
          {/* 网格线 */}
          {[0, 0.5, 1].map((r) => {
            const y = PAD_T + layout.innerH * (1 - r);
            return (
              <line
                key={`grid-${r}`}
                x1={PAD_L}
                y1={y}
                x2={PAD_L + layout.innerW}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.1}
                strokeDasharray="2 4"
              />
            );
          })}
          {/* 堆叠柱: 输入 + 输出 */}
          {layout.bars.map((bar, i) => (
            <g key={`bar-${i}`} opacity={activeIndex === null || activeIndex === i ? 1 : 0.45}>
              <rect
                x={bar.x}
                y={bar.inputY}
                width={layout.barW}
                height={bar.promptH}
                fill={COLOR_INPUT}
                rx={1}
                data-testid="usage-trend-bar-input"
              />
              <rect
                x={bar.x}
                y={bar.outputY}
                width={layout.barW}
                height={bar.completionH}
                fill={COLOR_OUTPUT}
                rx={1}
                data-testid="usage-trend-bar-output"
              />
            </g>
          ))}
          {/* 成本虚线（右轴） */}
          <path
            d={layout.costPath}
            fill="none"
            stroke={COLOR_COST}
            strokeWidth={1.5}
            strokeDasharray="3 2"
            data-testid="usage-trend-line-cost"
          />
          {/* 悬停参考线与高亮 */}
          {activeBar !== null && (
            <line
              x1={activeBar.centerX}
              y1={PAD_T}
              x2={activeBar.centerX}
              y2={PAD_T + layout.innerH}
              stroke="currentColor"
              strokeOpacity={0.35}
              strokeDasharray="2 3"
              data-testid="usage-trend-crosshair"
            />
          )}
          {/* 透明热区 */}
          {layout.bars.map((_bar, i) => (
            <rect
              key={`hit-${i}`}
              x={PAD_L + i * layout.slotW}
              y={PAD_T}
              width={layout.slotW}
              height={layout.innerH}
              fill="transparent"
              data-testid={`usage-trend-slot-${i}`}
              onMouseEnter={() => setActiveIndex(i)}
              onMouseMove={() => setActiveIndex(i)}
              onMouseLeave={() => setActiveIndex(null)}
              onPointerDown={() => setActiveIndex(i)}
            />
          ))}
          {/* X 轴 tick（起点/中点/终点） */}
          {layout.ticks.map((i) => {
            const bar = layout.bars[i];
            if (!bar) return null;
            return (
              <text
                key={`xt-${i}`}
                x={bar.centerX}
                y={SVG_H - 6}
                fontSize={10}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.6}
              >
                {formatTick(bar.raw.ts, bucket, i, series.length)}
              </text>
            );
          })}
          {/* Y 轴左标签: 最大 token 数 */}
          <text x={4} y={PAD_T + 10} fontSize={10} fill="currentColor" opacity={0.6}>
            {formatNumber(layout.maxTotal)}
          </text>
          {/* Y 轴右标签: 最大成本 */}
          <text
            x={SVG_W - 4}
            y={PAD_T + 10}
            fontSize={10}
            textAnchor="end"
            fill="currentColor"
            opacity={0.6}
          >
            {formatCost(layout.maxCost)}
          </text>
        </svg>
        {/* 详情卡 */}
        {active !== null && (
          <div
            role="tooltip"
            data-testid="usage-trend-tooltip"
            className={`pointer-events-none absolute z-10 w-56 rounded-radius-sm border border-border bg-bg-elevated p-2.5 text-ui-xs shadow-lg ${tooltipAlignClass}`}
            style={{ left: `${activeXPercent}%`, top: '4px' }}
          >
            <div className="mb-1.5 font-medium text-text" data-testid="usage-tooltip-period">
              {formatPeriodLabel(active.ts, bucket)}
            </div>
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-text-muted">
              <span>{t('settings.usage.tooltip.requests')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-requests">
                {active.requests}
              </span>
              <span>{t('settings.usage.tooltip.input')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-input">
                {formatNumber(active.prompt_tokens)}
              </span>
              <span>{t('settings.usage.tooltip.output')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-output">
                {formatNumber(active.completion_tokens)}
              </span>
              <span>{t('settings.usage.tooltip.total_tokens')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-total">
                {formatNumber(totalTokens(active))}
              </span>
              <span>{t('settings.usage.tooltip.cache_read')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-cache">
                {formatNumber(cacheRead(active))}
              </span>
              <span>{t('settings.usage.tooltip.cache_creation')}</span>
              <span className="text-right font-mono text-text">
                {formatNumber(cacheCreation(active))}
              </span>
              <span>{t('settings.usage.tooltip.cache_hit_rate')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-hit-rate">
                {formatPct(active.cache_hit_rate)}
              </span>
              <span>{t('settings.usage.tooltip.cost')}</span>
              <span className="text-right font-mono text-text" data-testid="usage-tooltip-cost">
                {formatCost(active.cost_usd)}
              </span>
            </div>
            {unknownRequests(active) > 0 && (
              <div
                className="mt-1.5 rounded-radius-sm bg-amber-500/10 px-1.5 py-0.5 text-ui-2xs text-amber-600 dark:text-amber-400"
                data-testid="usage-tooltip-partial"
              >
                {t('settings.usage.tooltip.partial_cost')} ({unknownRequests(active)})
              </div>
            )}
          </div>
        )}
        {/* 屏幕阅读器播报当前时段 */}
        <div className="sr-only" aria-live="polite" data-testid="usage-trend-aria">
          {active !== null
            ? `${formatPeriodLabel(active.ts, bucket)}: ${t('settings.usage.tooltip.requests')} ${active.requests}, ${t('settings.usage.tooltip.input')} ${active.prompt_tokens}, ${t('settings.usage.tooltip.output')} ${active.completion_tokens}, ${t('settings.usage.tooltip.cache_hit_rate')} ${formatPct(active.cache_hit_rate)}, ${t('settings.usage.tooltip.cost')} ${formatCost(active.cost_usd)}`
            : ''}
        </div>
      </div>
      <p className="mt-1 text-ui-2xs text-text-muted">{t('settings.usage.trend.hint')}</p>
    </Card>
  );
}
