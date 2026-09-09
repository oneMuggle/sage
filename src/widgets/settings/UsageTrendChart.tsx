/**
 * 用量趋势图 (L8 PR-C, 2026-09-09) — 自绘 SVG 双线图。
 *
 * 与 cc switch 风格接近: X 轴时间桶, Y 轴主指标 requests / 副指标 cost_usd。
 * 自绘而非引入 Recharts 的考量:
 * - Recharts (~95KB gzipped) 仅为一个简单折线图不划算
 * - 自绘 SVG 与现有 Tailwind/字号体系耦合更紧
 * - 颜色变量与 by-model 表格一致 (text-text / text-text-muted / accent)
 *
 * 设计要点:
 * - 单一系列 requests (主轴, 左 Y) + 副系列 cost_usd (右 Y, 可选隐藏)
 * - 数据空时显示占位提示 (避免裸空白让用户以为坏了)
 * - 桶时间格式按 bucket=hour/day 切: hour → "HH:00", day → "MM-DD"
 * - 错误态 (series 含 error 字段) 由父组件拦截, 这里只画数据
 */
import { useMemo } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type { UsageTrend, UsageTrendPoint } from '../../shared/api/usageApi';

const SVG_W = 600;
const SVG_H = 180;
const PAD_L = 36;
const PAD_R = 36;
const PAD_T = 16;
const PAD_B = 28;

function formatTick(ts: string, bucket: 'hour' | 'day', idx: number, total: number): string {
  if (!ts) return '';
  if (bucket === 'hour') {
    // "2026-09-09T07:00:00Z" → "07:00"
    const t = ts.indexOf('T');
    if (t < 0) return '';
    return ts.slice(t + 1, t + 6);
  }
  // day: "2026-09-09T00:00:00Z" → "09-09"
  if (idx === 0 || idx === total - 1) {
    // day bucket ISO 格式固定 10 字符宽 ("YYYY-MM-DD"), 直接 slice 5..10
    return ts.length >= 10 ? ts.slice(5, 10) : '';
  }
  return '';
}

function safeMax(values: number[]): number {
  let m = 0;
  for (const v of values) {
    if (v > m) m = v;
  }
  return m === 0 ? 1 : m;
}

function buildPath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return '';
  return points.map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`)).join(' ');
}

interface UsageTrendChartProps {
  trend: UsageTrend | null;
  loading: boolean;
}

export function UsageTrendChart({ trend, loading }: UsageTrendChartProps) {
  const { t } = useI18n();
  const series: UsageTrendPoint[] = trend?.series ?? [];
  const bucket = trend?.bucket ?? 'day';

  const layout = useMemo(() => {
    const innerW = SVG_W - PAD_L - PAD_R;
    const innerH = SVG_H - PAD_T - PAD_B;
    const maxReq = safeMax(series.map((p) => p.requests));
    const maxCost = safeMax(series.map((p) => p.cost_usd));
    const stepX = series.length > 1 ? innerW / (series.length - 1) : 0;
    const reqPoints = series.map((p, i) => ({
      x: PAD_L + i * stepX,
      y: PAD_T + innerH - (p.requests / maxReq) * innerH,
      raw: p,
    }));
    const costPoints = series.map((p, i) => ({
      x: PAD_L + i * stepX,
      y: PAD_T + innerH - (p.cost_usd / maxCost) * innerH,
    }));
    const ticks = [0, Math.floor(series.length / 2), series.length - 1].filter(
      (i) => i >= 0 && i < series.length,
    );
    return { innerW, innerH, maxReq, maxCost, reqPoints, costPoints, ticks };
  }, [series]);

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

  const reqPath = buildPath(layout.reqPoints);
  const costPath = buildPath(layout.costPoints);

  return (
    <div className="pt-2 border-t border-border" data-testid="usage-trend-chart">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-xs font-medium text-text">{t('settings.usage.trend.title')}</h4>
        <div className="flex gap-3 text-xs text-text-muted">
          <span data-testid="usage-trend-legend-requests">
            <span className="inline-block w-2 h-2 mr-1 align-middle bg-blue-500 rounded-full" />
            {t('settings.usage.trend.legendRequests')}
          </span>
          <span data-testid="usage-trend-legend-cost">
            <span className="inline-block w-2 h-2 mr-1 align-middle bg-amber-500 rounded-full" />
            {t('settings.usage.trend.legendCost')}
          </span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        className="w-full h-auto"
        role="img"
        aria-label={t('settings.usage.trend.title')}
      >
        {/* Y 轴网格线 (3 条) */}
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
        {/* Requests 线 (蓝) */}
        <path
          d={reqPath}
          fill="none"
          stroke="#3b82f6"
          strokeWidth={1.5}
          data-testid="usage-trend-line-requests"
        />
        {/* Cost 线 (琥珀) */}
        <path
          d={costPath}
          fill="none"
          stroke="#f59e0b"
          strokeWidth={1.5}
          strokeDasharray="3 2"
          data-testid="usage-trend-line-cost"
        />
        {/* 数据点 */}
        {layout.reqPoints.map((p, i) => (
          <circle key={`pt-${i}`} cx={p.x} cy={p.y} r={2} fill="#3b82f6" />
        ))}
        {/* X 轴 tick 标签 (起点/中点/终点) */}
        {layout.ticks.map((i) => {
          const p = layout.reqPoints[i];
          if (!p) return null;
          return (
            <text
              key={`xt-${i}`}
              x={p.x}
              y={SVG_H - 6}
              fontSize={10}
              textAnchor="middle"
              fill="currentColor"
              opacity={0.6}
            >
              {formatTick(p.raw.ts, bucket, i, series.length)}
            </text>
          );
        })}
        {/* Y 轴左标签: 最大请求数 */}
        <text x={4} y={PAD_T + 10} fontSize={10} fill="currentColor" opacity={0.6}>
          {Math.round(layout.maxReq)}
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
          ${layout.maxCost.toFixed(4)}
        </text>
      </svg>
    </div>
  );
}
