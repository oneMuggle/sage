/**
 * UsagePanel (M6 用量/成本面板) vitest
 *
 * mock desktopInvoke 的 invoke, 验证: 汇总渲染 / by-model 表格 /
 * 刷新按钮重调 / 错误态 / L8 PR-A cache 行 + range tab。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as desktopInvoke from '../../../shared/api/desktopInvoke';
import { I18nProvider } from '../../../shared/lib/i18n';
import { UsagePanel } from '../UsagePanel';

const SUMMARY = {
  totals: {
    requests: 3,
    prompt_tokens: 1000,
    completion_tokens: 500,
    cached_tokens: 0,
    cache_read_tokens: 600,
    cache_creation_tokens: 400,
    estimated_cost_usd: 0.0125,
  },
  by_model: [
    {
      model: 'gpt-4o',
      requests: 2,
      prompt_tokens: 800,
      completion_tokens: 400,
      cached_tokens: 0,
      cache_read_tokens: 500,
      cache_creation_tokens: 300,
      estimated_cost_usd: 0.01,
    },
    {
      model: 'local-model',
      requests: 1,
      prompt_tokens: 200,
      completion_tokens: 100,
      cached_tokens: 0,
      cache_read_tokens: 0,
      cache_creation_tokens: 0,
      estimated_cost_usd: null,
    },
  ],
  today: {
    requests: 1,
    prompt_tokens: 100,
    completion_tokens: 50,
    cached_tokens: 0,
    cache_read_tokens: 70,
    cache_creation_tokens: 30,
    estimated_cost_usd: 0.001,
  },
  cache_hit_rate: 0.6,
  range: 'today' as const,
};

function cloneSummary() {
  return JSON.parse(JSON.stringify(SUMMARY));
}

function renderPanel() {
  return render(
    <I18nProvider defaultLocale="zh">
      <UsagePanel />
    </I18nProvider>,
  );
}

describe('UsagePanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('渲染汇总数字与成本 (未知模型成本显示占位符)', async () => {
    const invokeSpy = vi.spyOn(desktopInvoke, 'invoke').mockResolvedValueOnce(cloneSummary());

    renderPanel();

    // L8 PR-A: 默认 range=today, 顶部汇总数字取自 today bucket (1 个请求)
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests').textContent).toBe('1');
    });
    expect(screen.getByTestId('usage-total-tokens').textContent).toBe('150');
    expect(screen.getByTestId('usage-total-cost').textContent).toBe('$0.0010');
    // by-model 表格: 两行, null 成本 → 占位符
    const table = screen.getByTestId('usage-by-model');
    expect(table.textContent).toContain('gpt-4o');
    expect(table.textContent).toContain('local-model');
    expect(table.textContent).toContain('—');
    expect(invokeSpy).toHaveBeenCalledWith('usage_summary', { range: 'today' });
  });

  it('刷新按钮重新请求数据', async () => {
    const invokeSpy = vi.spyOn(desktopInvoke, 'invoke').mockResolvedValue(cloneSummary());

    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests')).toBeDefined();
    });
    expect(invokeSpy).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('usage-refresh'));
    await waitFor(() => {
      expect(invokeSpy).toHaveBeenCalledTimes(2);
    });
  });

  it('请求失败显示错误提示', async () => {
    vi.spyOn(desktopInvoke, 'invoke').mockRejectedValueOnce(new Error('backend down'));

    renderPanel();

    await waitFor(() => {
      const errorEl = screen.getByTestId('usage-error');
      expect(errorEl.textContent).toContain('backend down');
    });
    expect(screen.queryByTestId('usage-by-model')).toBeNull();
  });

  // ==================== L8 PR-A (2026-09-09) ====================

  it('渲染 cache 拆分与命中率行', async () => {
    vi.spyOn(desktopInvoke, 'invoke').mockResolvedValueOnce(cloneSummary());

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId('usage-cache-row')).toBeDefined();
    });
    // today 模式默认选中, read/creation 来自 today bucket
    expect(screen.getByTestId('usage-cache-read').textContent).toBe('70');
    expect(screen.getByTestId('usage-cache-creation').textContent).toBe('30');
    // 0.6 * 100 = 60.0%
    expect(screen.getByTestId('usage-cache-hit-rate').textContent).toBe('60.0%');
  });

  it('切换 range tab 后重新请求并更新数字', async () => {
    const totalSummary = cloneSummary();
    totalSummary.range = 'total';
    totalSummary.totals.requests = 99;
    const invokeSpy = vi
      .spyOn(desktopInvoke, 'invoke')
      .mockResolvedValueOnce(cloneSummary()) // 初次 today
      .mockResolvedValueOnce(totalSummary); // 切到 total

    renderPanel();

    // 默认 today view, today.requests=1
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests').textContent).toBe('1');
    });
    expect(screen.getByTestId('usage-range-today').getAttribute('aria-selected')).toBe('true');

    fireEvent.click(screen.getByTestId('usage-range-total'));

    // 切到 total 后显示 totals.requests=99
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests').textContent).toBe('99');
    });
    expect(screen.getByTestId('usage-range-total').getAttribute('aria-selected')).toBe('true');
    // 第二次 invoke 必须带 range: total
    expect(invokeSpy).toHaveBeenNthCalledWith(2, 'usage_summary', { range: 'total' });
  });
});
