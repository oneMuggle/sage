/**
 * UsageTrendChart (L8 PR-C, 2026-09-09) vitest
 *
 * 验证三种 UI 状态:
 * - loading: 优先于 data, 即便 series 有数据也显示 loading 文案
 * - empty: series=[] 或 trend=null → 占位文案
 * - render: 正常 series → 两根 path + legend + ticks
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { UsageTrend } from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { UsageTrendChart } from '../UsageTrendChart';

function renderChart(props: { trend: UsageTrend | null; loading: boolean }) {
  return render(
    <I18nProvider defaultLocale="zh">
      <UsageTrendChart trend={props.trend} loading={props.loading} />
    </I18nProvider>,
  );
}

const SAMPLE_TREND: UsageTrend = {
  range: 'today',
  bucket: 'hour',
  series: [
    {
      ts: '2026-09-09T00:00:00Z',
      requests: 1,
      prompt_tokens: 100,
      completion_tokens: 20,
      cost_usd: 0.001,
      cache_hit_rate: 0.4,
    },
    {
      ts: '2026-09-09T06:00:00Z',
      requests: 5,
      prompt_tokens: 500,
      completion_tokens: 100,
      cost_usd: 0.005,
      cache_hit_rate: 0.5,
    },
    {
      ts: '2026-09-09T12:00:00Z',
      requests: 12,
      prompt_tokens: 1200,
      completion_tokens: 240,
      cost_usd: 0.012,
      cache_hit_rate: 0.6,
    },
    {
      ts: '2026-09-09T18:00:00Z',
      requests: 8,
      prompt_tokens: 800,
      completion_tokens: 160,
      cost_usd: 0.008,
      cache_hit_rate: 0.55,
    },
  ],
};

describe('UsageTrendChart', () => {
  it('loading=true 时优先显示加载文案', () => {
    renderChart({ trend: SAMPLE_TREND, loading: true });
    expect(screen.getByTestId('usage-trend-loading')).toBeDefined();
    expect(screen.queryByTestId('usage-trend-chart')).toBeNull();
    expect(screen.queryByTestId('usage-trend-empty')).toBeNull();
  });

  it('series 为空数组时显示占位提示', () => {
    renderChart({
      trend: { range: '7d', bucket: 'day', series: [] },
      loading: false,
    });
    expect(screen.getByTestId('usage-trend-empty')).toBeDefined();
    expect(screen.queryByTestId('usage-trend-chart')).toBeNull();
  });

  it('trend=null 时降级为空态 (与 series=[] 一致)', () => {
    renderChart({ trend: null, loading: false });
    expect(screen.getByTestId('usage-trend-empty')).toBeDefined();
  });

  it('有数据时渲染双线 + 图例 + Y 轴标签', () => {
    renderChart({ trend: SAMPLE_TREND, loading: false });
    const chart = screen.getByTestId('usage-trend-chart');
    expect(chart).toBeDefined();

    // 两条 path 都存在 (requests + cost_usd)
    const reqLine = screen.getByTestId('usage-trend-line-requests');
    const costLine = screen.getByTestId('usage-trend-line-cost');
    // d 属性以 M 开头 (M = moveTo, 自绘 SVG 起点)
    expect(reqLine.getAttribute('d')).toMatch(/^M /);
    expect(costLine.getAttribute('d')).toMatch(/^M /);
    // cost 是虚线 (strokeDasharray)
    expect(costLine.getAttribute('stroke-dasharray')).toBe('3 2');
    expect(reqLine.getAttribute('stroke-dasharray')).toBeNull();

    // 图例两条 (中点 i18n 文案 "请求数" / "成本")
    expect(screen.getByTestId('usage-trend-legend-requests').textContent).toContain('请求数');
    expect(screen.getByTestId('usage-trend-legend-cost').textContent).toContain('成本');

    // SVG 含 4 个数据点圆 (与 SAMPLE_TREND.series.length 一致)
    const circles = chart.querySelectorAll('circle');
    expect(circles.length).toBe(SAMPLE_TREND.series.length);
  });

  it('bucket=day 时中点 tick 留空 (避免 X 轴拥挤)', () => {
    const dayTrend: UsageTrend = {
      range: '30d',
      bucket: 'day',
      series: [
        {
          ts: '2026-08-10T00:00:00Z',
          requests: 2,
          prompt_tokens: 200,
          completion_tokens: 40,
          cost_usd: 0.002,
          cache_hit_rate: 0.3,
        },
        {
          ts: '2026-08-25T00:00:00Z',
          requests: 4,
          prompt_tokens: 400,
          completion_tokens: 80,
          cost_usd: 0.004,
          cache_hit_rate: 0.35,
        },
        {
          ts: '2026-09-09T00:00:00Z',
          requests: 6,
          prompt_tokens: 600,
          completion_tokens: 120,
          cost_usd: 0.006,
          cache_hit_rate: 0.4,
        },
      ],
    };
    renderChart({ trend: dayTrend, loading: false });
    const chart = screen.getByTestId('usage-trend-chart');
    // day bucket 下, idx=1 (中点) tick 文本应为空, 只有起点 + 终点有 "08-10" / "09-09"
    const texts = Array.from(chart.querySelectorAll('text'))
      .map((t) => t.textContent ?? '')
      .filter((s) => /^\d{2}-\d{2}$/.test(s));
    expect(texts.length).toBe(2);
  });
});
