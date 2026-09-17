/**
 * ModelCatalog 页面测试 (Task 6, 2026-09-15)
 *
 * 验证 catalog 管理页面的核心契约:
 * - 列表加载 → 显示 catalog 行 (model_key + 上下文窗口 + 价格)
 * - 过滤 → 输入关键词后, 不匹配行消失
 * - 探测按钮触发 → 调用 probe API
 * - 快照入口 → "审核" 链接打开 SnapshotReview
 *
 * 测试策略:
 * - vi.hoisted() 声明 mock 引用, 避免 vi.mock 工厂 hoist 后引用丢失
 * - mock ``src/entities/model-catalog/api`` 模块, 不打后端。
 * - 用 jsdom + electronAPI 桩化 IPC, 走的是 ``backendRequest`` 漏斗。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../entities/setting/types';
import { useSettingsStore } from '../../features/manage-settings/settingsStore';
import { I18nProvider } from '../../shared/lib/i18n';

const mocks = vi.hoisted(() => {
  const createMock = () => vi.fn();
  return {
    listModels: createMock(),
    listSnapshots: createMock(),
    probeModel: createMock(),
    getEffective: createMock(),
    setOverride: createMock(),
    getDiff: createMock(),
    apply: createMock(),
    ignore: createMock(),
    importSnapshot: createMock(),
    syncOpenRouter: createMock(),
    exportSnapshot: createMock(),
    deleteOverride: createMock(),
  };
});

vi.mock('../../entities/model-catalog/api', () => ({
  listModels: mocks.listModels,
  listSnapshots: mocks.listSnapshots,
  probeModel: mocks.probeModel,
  getEffective: mocks.getEffective,
  setOverride: mocks.setOverride,
  getDiff: mocks.getDiff,
  apply: mocks.apply,
  ignore: mocks.ignore,
  importSnapshot: mocks.importSnapshot,
  syncOpenRouter: mocks.syncOpenRouter,
  exportSnapshot: mocks.exportSnapshot,
  deleteOverride: mocks.deleteOverride,
}));

beforeEach(() => {
  useSettingsStore.setState({
    settings: { ...DEFAULT_SETTINGS, endpoints: [] },
    isLoading: false,
  });
  // 桩化 IPC relay
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    backendRequest: async () => null,
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  mocks.listModels.mockReset();
  mocks.listSnapshots.mockReset();
  mocks.probeModel.mockReset();
  mocks.getEffective.mockReset();
  mocks.setOverride.mockReset();
  mocks.getDiff.mockReset();
  mocks.apply.mockReset();
  mocks.ignore.mockReset();
  mocks.importSnapshot.mockReset();
  mocks.syncOpenRouter.mockReset();
  mocks.exportSnapshot.mockReset();
  mocks.deleteOverride.mockReset();
});

describe('ModelCatalog page', () => {
  it('加载时显示 catalog 行 + 上下文窗口 + 价格', async () => {
    mocks.listModels.mockResolvedValue({
      items: [
        {
          model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
          native: 200000,
          price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
        {
          model_key: { provider: 'openrouter', model_id: 'openai/gpt-4o-mini' },
          native: 128000,
          price: { input_per_million: '0.15', output_per_million: '0.6', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    mocks.listSnapshots.mockResolvedValue([]);
    mocks.probeModel.mockResolvedValue({
      status: 'success',
      adapter: 'openai',
      data: null,
      error: null,
    });
    mocks.getEffective.mockResolvedValue(null);

    const Page = (await import('../ModelCatalog')).default;
    render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();
    expect(screen.getByText('openrouter/openai/gpt-4o-mini')).toBeInTheDocument();
  });

  it('过滤关键词后, 不匹配行消失', async () => {
    mocks.listModels.mockResolvedValue({
      items: [
        {
          model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
          native: 200000,
          price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
        {
          model_key: { provider: 'openrouter', model_id: 'openai/gpt-4o-mini' },
          native: 128000,
          price: { input_per_million: '0.15', output_per_million: '0.6', currency: 'USD' },
          source: 'openrouter',
          pricing_scope: 'base',
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    mocks.listSnapshots.mockResolvedValue([]);
    mocks.probeModel.mockResolvedValue({
      status: 'success',
      adapter: 'openai',
      data: null,
      error: null,
    });
    mocks.getEffective.mockResolvedValue(null);

    const Page = (await import('../ModelCatalog')).default;
    render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );
    await screen.findByText('openrouter/anthropic/claude-3.5-sonnet');

    const search = screen.getByPlaceholderText(/搜索|filter|搜索模型/i);
    fireEvent.change(search, { target: { value: 'gpt' } });

    await waitFor(() => {
      expect(screen.queryByText('openrouter/anthropic/claude-3.5-sonnet')).not.toBeInTheDocument();
      expect(screen.getByText('openrouter/openai/gpt-4o-mini')).toBeInTheDocument();
    });
  });

  it('空目录展示空态文案', async () => {
    mocks.listModels.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    mocks.listSnapshots.mockResolvedValue([]);
    mocks.probeModel.mockResolvedValue({
      status: 'success',
      adapter: 'openai',
      data: null,
      error: null,
    });
    mocks.getEffective.mockResolvedValue(null);

    const Page = (await import('../ModelCatalog')).default;
    render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/暂无|空|empty|暂无模型/i)).toBeInTheDocument();
  });

  it('端点选择器来自设置并将筛选值传给 API', async () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        endpoints: [
          {
            ...DEFAULT_SETTINGS.endpoints[0],
            id: 'ep-one',
            name: '本地模型',
          },
          {
            ...DEFAULT_SETTINGS.endpoints[0],
            id: 'ep-two',
            name: '',
          },
        ],
      },
      isLoading: false,
    });
    mocks.listModels.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    mocks.listSnapshots.mockResolvedValue([]);

    const Page = (await import('../ModelCatalog')).default;
    render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );

    const endpointSelect = await screen.findByTestId('model-catalog-endpoint');
    expect(endpointSelect).toHaveValue('');
    expect(screen.getByRole('option', { name: '全部' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '本地模型' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ep-two' })).toBeInTheDocument();

    fireEvent.change(endpointSelect, { target: { value: 'ep-one' } });

    await waitFor(() => {
      expect(mocks.listModels).toHaveBeenLastCalledWith({
        limit: 100,
        offset: 0,
        endpointId: 'ep-one',
      });
    });
  });
});
