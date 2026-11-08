// @vitest-environment jsdom
/**
 * P0-B (2026-09-18): 端点限额用量区块 — 进度/预警阈值/未归属聚合/成本未知降级。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import * as usageApi from '../../../shared/api/usageApi';
import { EndpointQuotaSection } from '../EndpointQuotaSection';

function makeSettings() {
  return {
    ...DEFAULT_SETTINGS,
    endpoints: [
      {
        ...DEFAULT_SETTINGS.endpoints[0],
        id: 'ep-warn',
        name: 'AgnesAI',
        quota: { dailyTokens: 100000 },
      },
      {
        ...DEFAULT_SETTINGS.endpoints[0],
        id: 'ep-over',
        name: 'OpenAI',
        quota: { monthlyBudgetUsd: 20 },
      },
      {
        ...DEFAULT_SETTINGS.endpoints[0],
        id: 'ep-unknown-cost',
        name: 'Local',
        quota: { monthlyBudgetUsd: 5 },
      },
      {
        ...DEFAULT_SETTINGS.endpoints[0],
        id: 'ep-free',
        name: 'Ollama',
      },
    ],
  };
}

const ITEMS = [
  {
    endpoint_id: 'ep-warn',
    total_requests: 10,
    total_tokens: 200000,
    today_requests: 5,
    today_tokens: 85000,
    month_requests: 5,
    month_tokens: 85000,
    month_cost_usd: 0.5,
  },
  {
    endpoint_id: 'ep-over',
    total_requests: 3,
    total_tokens: 50000,
    today_requests: 1,
    today_tokens: 20000,
    month_requests: 3,
    month_tokens: 50000,
    month_cost_usd: 25.0,
  },
  {
    endpoint_id: 'ep-unknown-cost',
    total_requests: 1,
    total_tokens: 10,
    today_requests: 1,
    today_tokens: 10,
    month_requests: 1,
    month_tokens: 10,
    month_cost_usd: null,
  },
  {
    // 已删除端点的历史用量 → 归入"未归属端点"
    endpoint_id: 'ghost',
    total_requests: 2,
    total_tokens: 999,
    today_requests: 0,
    today_tokens: 0,
    month_requests: 0,
    month_tokens: 0,
    month_cost_usd: null,
  },
];

describe('EndpointQuotaSection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState({ settings: makeSettings() });
    vi.spyOn(usageApi, 'fetchUsageByEndpoint').mockResolvedValue({
      items: ITEMS,
      day_start_utc: '2026-09-18T00:00:00Z',
      month_start_utc: '2026-09-01T00:00:00Z',
    });
  });

  it('80% 预警 / 100% 超限 / 成本未知 / 未设限额 / 未归属端点', async () => {
    render(<EndpointQuotaSection />);

    const warnRow = await screen.findByTestId('quota-row-ep-warn');
    expect(warnRow.textContent).toContain('接近限额');
    expect(warnRow.textContent).toContain('85K / 100K');

    const overRow = screen.getByTestId('quota-row-ep-over');
    expect(overRow.textContent).toContain('已超出限额');
    expect(overRow.textContent).toContain('$25.00 / $20.00');

    const unknownCost = screen.getByTestId('quota-row-ep-unknown-cost');
    expect(unknownCost.textContent).toContain('本月成本未知');

    expect(screen.getByTestId('quota-row-ep-free').textContent).toContain('未设限额');
    expect(screen.getByTestId('quota-row-orphan').textContent).toContain('未归属端点');
  });

  it('接口报错时显示错误条且不崩溃', async () => {
    vi.spyOn(usageApi, 'fetchUsageByEndpoint').mockRejectedValue(new Error('backend down'));
    render(<EndpointQuotaSection />);
    expect(await screen.findByTestId('endpoint-quota-error')).toHaveTextContent('backend down');
  });
});
