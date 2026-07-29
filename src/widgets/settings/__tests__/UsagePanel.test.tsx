/**
 * UsagePanel (M6 用量/成本面板) vitest
 *
 * mock desktopInvoke 的 invoke, 验证: 汇总渲染 / by-model 表格 /
 * 刷新按钮重调 / 错误态。
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
    estimated_cost_usd: 0.0125,
  },
  by_model: [
    {
      model: 'gpt-4o',
      requests: 2,
      prompt_tokens: 800,
      completion_tokens: 400,
      estimated_cost_usd: 0.01,
    },
    {
      model: 'local-model',
      requests: 1,
      prompt_tokens: 200,
      completion_tokens: 100,
      estimated_cost_usd: null,
    },
  ],
  today: {
    requests: 1,
    prompt_tokens: 100,
    completion_tokens: 50,
    estimated_cost_usd: 0.001,
  },
};

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
    const invokeSpy = vi
      .spyOn(desktopInvoke, 'invoke')
      .mockResolvedValueOnce(JSON.parse(JSON.stringify(SUMMARY)));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests').textContent).toBe('3');
    });
    expect(screen.getByTestId('usage-total-tokens').textContent).toBe('1,500');
    expect(screen.getByTestId('usage-total-cost').textContent).toBe('$0.0125');
    // by-model 表格: 两行, null 成本 → 占位符
    const table = screen.getByTestId('usage-by-model');
    expect(table.textContent).toContain('gpt-4o');
    expect(table.textContent).toContain('local-model');
    expect(table.textContent).toContain('—');
    expect(invokeSpy).toHaveBeenCalledWith('usage_summary');
  });

  it('刷新按钮重新请求数据', async () => {
    const invokeSpy = vi
      .spyOn(desktopInvoke, 'invoke')
      .mockResolvedValue(JSON.parse(JSON.stringify(SUMMARY)));

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
});
