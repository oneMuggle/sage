/**
 * UsageRequestsTable (L8 PR-B, 2026-09-09) vitest
 *
 * 验证: 子组件独立加载 / 渲染分页列表 / 翻页按钮 / 空态 / 错误态。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as usageApi from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { UsageRequestsTable } from '../UsageRequestsTable';

const ROW = {
  id: 'row-1',
  session_id: 'sess-1',
  model: 'gpt-4o',
  prompt_tokens: 100,
  completion_tokens: 50,
  total_tokens: 150,
  cached_tokens: 0,
  cache_read_tokens: 70,
  cache_creation_tokens: 30,
  estimated_cost_usd: 0.001,
  created_at_ms: 1700000000000,
  created_at_iso: '2023-11-14T22:13:20Z',
};

function pageWith(rows: (typeof ROW)[], total = rows.length, offset = 0) {
  return { items: rows, total, limit: 20, offset };
}

describe('UsageRequestsTable', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('挂载时拉取第一页, 渲染 6 列', async () => {
    const spy = vi
      .spyOn(usageApi, 'fetchUsageRequests')
      .mockResolvedValueOnce(pageWith([ROW, { ...ROW, id: 'row-2', model: 'claude-opus' }], 2));

    render(
      <I18nProvider defaultLocale="zh">
        <UsageRequestsTable />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('usage-requests-rows')).toBeDefined();
    });
    // 6 个表头
    const headers = screen.getAllByRole('columnheader');
    expect(headers).toHaveLength(6);
    // 2 行数据 + thead
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBe(2 + 1);
    expect(screen.getByText('gpt-4o')).toBeDefined();
    expect(screen.getByText('claude-opus')).toBeDefined();
    // pageInfo 反映总数 2
    expect(screen.getByTestId('usage-requests-pageinfo').textContent).toContain('2');
    expect(spy).toHaveBeenCalledWith({ limit: 20, offset: 0 });
  });

  it('空数据展示 empty 文案', async () => {
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValueOnce(pageWith([], 0));

    render(
      <I18nProvider defaultLocale="zh">
        <UsageRequestsTable />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('usage-requests-empty')).toBeDefined();
    });
    expect(screen.queryByTestId('usage-requests-rows')).toBeNull();
    // 空数据时 pageInfo 不显示
    expect(screen.getByTestId('usage-requests-pageinfo').textContent).toBe('');
  });

  it('请求失败展示错误提示', async () => {
    vi.spyOn(usageApi, 'fetchUsageRequests').mockRejectedValueOnce(new Error('db locked'));

    render(
      <I18nProvider defaultLocale="zh">
        <UsageRequestsTable />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('usage-requests-error')).toBeDefined();
    });
    expect(screen.getByTestId('usage-requests-error').textContent).toContain('db locked');
  });

  it('点击下一页重新请求带 offset', async () => {
    const spy = vi
      .spyOn(usageApi, 'fetchUsageRequests')
      .mockResolvedValueOnce(pageWith([ROW], 50, 0))
      .mockResolvedValueOnce(pageWith([{ ...ROW, id: 'row-2' }], 50, 20));

    render(
      <I18nProvider defaultLocale="zh">
        <UsageRequestsTable />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('usage-requests-next')).toBeDefined();
    });
    // 第一页后 next 可点, prev 不可点
    expect(screen.getByTestId('usage-requests-next')).not.toBeDisabled();
    expect(screen.getByTestId('usage-requests-prev')).toBeDisabled();

    fireEvent.click(screen.getByTestId('usage-requests-next'));

    await waitFor(() => {
      expect(spy).toHaveBeenCalledTimes(2);
    });
    expect(spy).toHaveBeenNthCalledWith(2, { limit: 20, offset: 20 });
    // 翻页后 prev 可点
    await waitFor(() => {
      expect(screen.getByTestId('usage-requests-prev')).not.toBeDisabled();
    });
  });
});
