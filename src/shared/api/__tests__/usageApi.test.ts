/**
 * r85: usageApi 单元测试——fetchUsageSummary / fetchUsageRequests /
 * fetchSessionUsage / fetchUsageTrend / fetchUsageCsvExport。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import {
  fetchUsageSummary,
  fetchUsageRequests,
  fetchSessionUsage,
  fetchUsageTrend,
  fetchUsageCsvExport,
} from '../usageApi';

beforeEach(() => { mockInvoke.mockReset(); });

describe('usageApi', () => {
  it('fetchUsageSummary() passes range and returns data', async () => {
    const summary = { totals: { requests: 5 }, range: '7d' };
    mockInvoke.mockResolvedValueOnce(summary);
    const r = await fetchUsageSummary('7d');
    expect(mockInvoke).toHaveBeenCalledWith('usage_summary', { range: '7d' });
    expect(r).toEqual(summary);
  });

  it('fetchUsageSummary() without range omits key', async () => {
    mockInvoke.mockResolvedValueOnce({ totals: {} });
    await fetchUsageSummary();
    expect(mockInvoke).toHaveBeenCalledWith('usage_summary', undefined);
  });

  it('fetchUsageRequests() passes params and returns page', async () => {
    const page = { items: [{ id: 'r1' }], total: 1, limit: 20, offset: 0 };
    mockInvoke.mockResolvedValueOnce(page);
    const r = await fetchUsageRequests({ limit: 20, offset: 0 });
    expect(mockInvoke).toHaveBeenCalledWith('usage_list_requests', { limit: 20, offset: 0 });
    expect(r).toEqual(page);
  });

  it('fetchSessionUsage() passes sessionId', async () => {
    const data = { session_id: 's1', total_tokens: 100 };
    mockInvoke.mockResolvedValueOnce(data);
    const r = await fetchSessionUsage('s1');
    expect(mockInvoke).toHaveBeenCalledWith('usage_get_session', { sessionId: 's1' });
    expect(r).toEqual(data);
  });

  it('fetchUsageTrend() passes params', async () => {
    const trend = { points: [] };
    mockInvoke.mockResolvedValueOnce(trend);
    await fetchUsageTrend({ range: '7d' });
    expect(mockInvoke).toHaveBeenCalledWith('usage_trend', { range: '7d' });
  });

  it('fetchUsageCsvExport() returns CSV string', async () => {
    mockInvoke.mockResolvedValueOnce('col1,col2\n1,2');
    const r = await fetchUsageCsvExport({ range: 'total' });
    expect(r).toBe('col1,col2\n1,2');
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('backend down'));
    await expect(fetchUsageSummary()).rejects.toThrow('backend down');
  });
});
