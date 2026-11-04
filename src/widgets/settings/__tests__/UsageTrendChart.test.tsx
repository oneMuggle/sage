/**
 * UsageTrendChart — 堆叠柱 + 分时段 hover 详情卡 vitest
 *
 * 覆盖:
 * - loading / empty 状态优先级
 * - 堆叠柱、成本虚线、图例渲染
 * - hover 命中时段 → 详情卡展示请求/token/缓存/成本/部分估算
 * - 鼠标离开隐藏详情卡
 * - 键盘 ←/→/Home/End/Esc 切换与关闭
 * - 日槽仅首尾显示 X 轴标签
 * - Markdown / JSON 导出格式
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { UsageTrend } from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import {
  formatPeriodLabel,
  formatUsageTrendJson,
  formatUsageTrendMarkdown,
  UsageTrendChart,
} from '../UsageTrendChart';

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
      ts: '2026-09-09T00:00:00',
      requests: 1,
      prompt_tokens: 100,
      completion_tokens: 20,
      total_tokens: 120,
      cache_read_tokens: 40,
      cache_creation_tokens: 10,
      cost_usd: 0.001,
      cache_hit_rate: 0.4,
      known_requests: 1,
      unknown_requests: 0,
    },
    {
      ts: '2026-09-09T06:00:00',
      requests: 5,
      prompt_tokens: 500,
      completion_tokens: 100,
      total_tokens: 600,
      cache_read_tokens: 200,
      cache_creation_tokens: 50,
      cost_usd: 0.005,
      cache_hit_rate: 0.5,
      known_requests: 5,
      unknown_requests: 0,
    },
    {
      ts: '2026-09-09T12:00:00',
      requests: 12,
      prompt_tokens: 1200,
      completion_tokens: 240,
      total_tokens: 1440,
      cache_read_tokens: 600,
      cache_creation_tokens: 100,
      cost_usd: 0.012,
      cache_hit_rate: 0.6,
      known_requests: 10,
      unknown_requests: 2,
    },
    {
      ts: '2026-09-09T18:00:00',
      requests: 8,
      prompt_tokens: 800,
      completion_tokens: 160,
      total_tokens: 960,
      cache_read_tokens: 400,
      cache_creation_tokens: 80,
      cost_usd: 0.008,
      cache_hit_rate: 0.55,
      known_requests: 8,
      unknown_requests: 0,
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

  it('有数据时渲染输入/输出曲线 + 面积 + 成本虚线 + 图例', () => {
    renderChart({ trend: SAMPLE_TREND, loading: false });
    const chart = screen.getByTestId('usage-trend-chart');
    expect(chart).toBeDefined();

    const inputLine = screen.getByTestId('usage-trend-line-input');
    const outputLine = screen.getByTestId('usage-trend-line-output');
    expect(inputLine.getAttribute('d')).toMatch(/^M /);
    expect(outputLine.getAttribute('d')).toMatch(/^M /);
    // 曲线下方渐变面积存在
    expect(screen.getByTestId('usage-trend-area-input').getAttribute('d')).toContain('Z');
    expect(screen.getByTestId('usage-trend-area-output').getAttribute('d')).toContain('Z');

    const costLine = screen.getByTestId('usage-trend-line-cost');
    expect(costLine.getAttribute('d')).toMatch(/^M /);
    expect(costLine.getAttribute('stroke-dasharray')).toBe('3 2');

    expect(screen.getByTestId('usage-trend-legend-cost').textContent).toContain('成本');
    // hover 前无详情卡与参考线
    expect(screen.queryByTestId('usage-trend-tooltip')).toBeNull();
    expect(screen.queryByTestId('usage-trend-crosshair')).toBeNull();
  });

  it('hover 时段显示完整详情卡（含部分估算标记）', () => {
    renderChart({ trend: SAMPLE_TREND, loading: false });

    fireEvent.mouseEnter(screen.getByTestId('usage-trend-slot-2'));

    const tooltip = screen.getByTestId('usage-trend-tooltip');
    expect(tooltip).toBeDefined();
    expect(screen.getByTestId('usage-tooltip-period').textContent).toBe('09/09 12:00–13:00');
    expect(screen.getByTestId('usage-tooltip-requests').textContent).toBe('12');
    expect(screen.getByTestId('usage-tooltip-input').textContent).toBe('1.2K');
    expect(screen.getByTestId('usage-tooltip-output').textContent).toBe('240');
    expect(screen.getByTestId('usage-tooltip-total').textContent).toBe('1.4K');
    expect(screen.getByTestId('usage-tooltip-cache').textContent).toBe('600');
    expect(screen.getByTestId('usage-tooltip-hit-rate').textContent).toBe('60.0%');
    expect(screen.getByTestId('usage-tooltip-cost').textContent).toBe('$0.01');
    expect(screen.getByTestId('usage-tooltip-partial').textContent).toContain('含未定价请求');
    expect(screen.getByTestId('usage-trend-crosshair')).toBeDefined();
  });

  it('鼠标离开后隐藏详情卡', () => {
    renderChart({ trend: SAMPLE_TREND, loading: false });
    const slot = screen.getByTestId('usage-trend-slot-1');
    fireEvent.mouseEnter(slot);
    expect(screen.getByTestId('usage-trend-tooltip')).toBeDefined();
    fireEvent.mouseLeave(slot);
    expect(screen.queryByTestId('usage-trend-tooltip')).toBeNull();
  });

  it('键盘导航切换与关闭详情卡', () => {
    renderChart({ trend: SAMPLE_TREND, loading: false });
    const chart = screen.getByTestId('usage-trend-chart');

    // 聚焦默认选中最后一个时段
    fireEvent.focus(chart);
    expect(screen.getByTestId('usage-tooltip-period').textContent).toBe('09/09 18:00–19:00');

    fireEvent.keyDown(chart, { key: 'ArrowLeft' });
    expect(screen.getByTestId('usage-tooltip-period').textContent).toBe('09/09 12:00–13:00');

    fireEvent.keyDown(chart, { key: 'Home' });
    expect(screen.getByTestId('usage-tooltip-period').textContent).toBe('09/09 00:00–01:00');

    fireEvent.keyDown(chart, { key: 'End' });
    expect(screen.getByTestId('usage-tooltip-period').textContent).toBe('09/09 18:00–19:00');

    fireEvent.keyDown(chart, { key: 'Escape' });
    expect(screen.queryByTestId('usage-trend-tooltip')).toBeNull();
  });

  it('范围切换后 activeIndex 越界不会崩溃', () => {
    const { rerender } = renderChart({ trend: SAMPLE_TREND, loading: false });
    fireEvent.mouseEnter(screen.getByTestId('usage-trend-slot-3'));
    expect(screen.getByTestId('usage-trend-tooltip')).toBeDefined();

    const shorter: UsageTrend = {
      range: 'today',
      bucket: 'hour',
      series: SAMPLE_TREND.series.slice(0, 1),
    };
    rerender(
      <I18nProvider defaultLocale="zh">
        <UsageTrendChart trend={shorter} loading={false} />
      </I18nProvider>,
    );
    expect(screen.getByTestId('usage-trend-chart')).toBeDefined();
    expect(screen.queryByTestId('usage-trend-tooltip')).toBeNull();
  });

  it('bucket=day 时仅首尾显示 X 轴日期标签', () => {
    const dayTrend: UsageTrend = {
      range: '30d',
      bucket: 'day',
      series: [
        {
          ts: '2026-08-10T00:00:00',
          requests: 2,
          prompt_tokens: 200,
          completion_tokens: 40,
          cost_usd: 0.002,
          cache_hit_rate: 0.3,
        },
        {
          ts: '2026-08-25T00:00:00',
          requests: 4,
          prompt_tokens: 400,
          completion_tokens: 80,
          cost_usd: 0.004,
          cache_hit_rate: 0.35,
        },
        {
          ts: '2026-09-09T00:00:00',
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
    const texts = Array.from(chart.querySelectorAll('text'))
      .map((t) => t.textContent ?? '')
      .filter((s) => /^\d{2}-\d{2}$/.test(s));
    expect(texts).toEqual(['08-10', '09-09']);
  });

  it('formatPeriodLabel 处理小时槽与日槽', () => {
    expect(formatPeriodLabel('2026-09-09T23:00:00', 'hour')).toBe('09/09 23:00–00:00');
    expect(formatPeriodLabel('2026-09-09T00:00:00', 'day')).toBe('09/09');
    expect(formatPeriodLabel('not-a-date', 'day')).toBe('not-a-date');
  });

  it('formats usage trend as Markdown and JSON', () => {
    const md = formatUsageTrendMarkdown(SAMPLE_TREND);
    expect(md).toContain('# 用量趋势 (today · hour)');
    expect(md).toContain('- 数据点数: 4');
    expect(md).toContain('缓存命中 40 / 创建 10');
    const json = JSON.parse(formatUsageTrendJson(SAMPLE_TREND));
    expect(json.range).toBe('today');
    expect(json.count).toBe(4);
  });
});
