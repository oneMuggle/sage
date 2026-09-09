/**
 * UsagePanel (M6 用量/成本面板) vitest
 *
 * mock desktopInvoke 的 invoke, 验证: 汇总渲染 / by-model 表格 /
 * 刷新按钮重调 / 错误态 / L8 PR-A cache 行 + range tab。
 *
 * L8 PR-B (2026-09-09): 引入 UsageRequestsTable 子组件, 它会并发调
 * usage_list_requests — mock 用 mockResolvedValue 给出持久默认值,
 * 避免子组件 fetch 失败抛 unhandled rejection。
 *
 * 注意: vi.spyOn(module, 'fn') 在 vitest+ESM 下不可靠地替换命名导出
 * (实测 spy 后 module.invoke 仍指向原函数), 改用 mockImplementation
 * 直接覆盖 spy 行为 — UsagePanel 通过 usageApi 的 wrapper 调用,
 * spy 后 usageApi 拿到的引用未必更新, 因此本测试改 mock usageApi 模块
 * 的导出函数, 保证覆盖 UsagePanel / UsageRequestsTable 两条调用链。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as usageApi from '../../../shared/api/usageApi';
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

  // L8 PR-C: 子组件 UsageTrendChart 会并发调 fetchUsageTrend —
  // 默认空 series, 让现有断言不受新 fetch 通道影响。
  function mockTrendAndCsv() {
    vi.spyOn(usageApi, 'fetchUsageTrend').mockResolvedValue({
      range: 'today',
      bucket: 'hour',
      series: [],
    });
    vi.spyOn(usageApi, 'fetchUsageCsvExport').mockResolvedValue('time,model,tokens,cost\n');
  }

  it('渲染汇总数字与成本 (未知模型成本显示占位符)', async () => {
    const summarySpy = vi
      .spyOn(usageApi, 'fetchUsageSummary')
      .mockResolvedValueOnce(cloneSummary());
    // L8 PR-B: 子组件 fetchUsageRequests 默认空页
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    mockTrendAndCsv();

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
    expect(summarySpy).toHaveBeenCalledWith('today');
  });

  it('刷新按钮重新请求数据', async () => {
    const summarySpy = vi.spyOn(usageApi, 'fetchUsageSummary').mockResolvedValue(cloneSummary());
    // L8 PR-B: 子组件 fetchUsageRequests 默认空页 (mockResolvedValue 持久)
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    mockTrendAndCsv();

    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests')).toBeDefined();
    });
    expect(summarySpy).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('usage-refresh'));
    await waitFor(() => {
      expect(summarySpy).toHaveBeenCalledTimes(2);
    });
  });

  it('请求失败显示错误提示', async () => {
    vi.spyOn(usageApi, 'fetchUsageSummary').mockRejectedValueOnce(new Error('backend down'));
    // L8 PR-B: 子组件 list 通道也抛错, 验证独立错误路径
    vi.spyOn(usageApi, 'fetchUsageRequests').mockRejectedValue(new Error('list unavailable'));
    mockTrendAndCsv();

    renderPanel();

    await waitFor(() => {
      const errorEl = screen.getByTestId('usage-error');
      expect(errorEl.textContent).toContain('backend down');
    });
    expect(screen.queryByTestId('usage-by-model')).toBeNull();
  });

  // ==================== L8 PR-A (2026-09-09) ====================

  it('渲染 cache 拆分与命中率行', async () => {
    vi.spyOn(usageApi, 'fetchUsageSummary').mockResolvedValueOnce(cloneSummary());
    // L8 PR-B: 子组件默认空页
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    mockTrendAndCsv();

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
    const summarySpy = vi
      .spyOn(usageApi, 'fetchUsageSummary')
      .mockResolvedValueOnce(cloneSummary()) // 初次 today
      .mockResolvedValueOnce(totalSummary); // 切到 total
    // L8 PR-B: 子组件 fetchUsageRequests 持久空页
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    mockTrendAndCsv();

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
    expect(summarySpy).toHaveBeenNthCalledWith(2, 'total');
  });

  // ==================== L8 PR-C (2026-09-09) ====================

  it('CSV 导出按钮触发 fetchUsageCsvExport 并下载 (带 BOM 与文件名)', async () => {
    vi.spyOn(usageApi, 'fetchUsageSummary').mockResolvedValueOnce(cloneSummary());
    vi.spyOn(usageApi, 'fetchUsageRequests').mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const csvSpy = vi
      .spyOn(usageApi, 'fetchUsageCsvExport')
      .mockResolvedValue('time,model,tokens\n2026-09-09,gpt-4o,1500\n');
    vi.spyOn(usageApi, 'fetchUsageTrend').mockResolvedValue({
      range: 'today',
      bucket: 'hour',
      series: [],
    });

    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId('usage-total-requests')).toBeDefined();
    });

    // 拦截 a.click() — jsdom 不真下载, 验证 URL.createObjectURL + 链接属性
    const createUrl = vi.fn(() => 'blob:test');
    const revokeUrl = vi.fn();
    let clickedDownload = '';
    let blobText = '';
    const realCreate = URL.createObjectURL;
    const realRevoke = URL.revokeObjectURL;
    const realCreateEl = document.createElement.bind(document);
    URL.createObjectURL = createUrl;
    URL.revokeObjectURL = revokeUrl;
    document.createElement = ((tag: string) => {
      const el = realCreateEl(tag);
      if (tag === 'a') {
        (el as HTMLAnchorElement).click = function (this: HTMLAnchorElement) {
          // 仅记录下载名, 不要触碰 blobText (BOM 由 Blob 子类捕获)
          clickedDownload = this.download;
        };
      }
      return el;
    }) as typeof document.createElement;
    // Blob 子类取首 part 验证 BOM
    const realBlob = global.Blob;
    global.Blob = class extends realBlob {
      constructor(parts: BlobPart[], init?: BlobPropertyBag) {
        if (parts.length > 0) {
          blobText = String(parts[0]).slice(0, 1);
        }
        super(parts, init);
      }
    } as typeof Blob;

    fireEvent.click(screen.getByTestId('usage-export-csv'));

    await waitFor(() => {
      expect(csvSpy).toHaveBeenCalledWith({ range: 'today' });
    });
    // BOM 写入 (UTF-8 0xEF 0xBB 0xBF 渲染为 '\uFEFF' 一个字符)
    expect(blobText).toBe('\uFEFF');
    // createObjectURL / revokeObjectURL 都调过
    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalledTimes(1);
    // 文件名带 range + timestamp
    expect(clickedDownload.startsWith('sage-usage-today-')).toBe(true);
    expect(clickedDownload.endsWith('.csv')).toBe(true);

    // 还原全局
    URL.createObjectURL = realCreate;
    URL.revokeObjectURL = realRevoke;
    document.createElement = realCreateEl;
    global.Blob = realBlob;
  });
});
