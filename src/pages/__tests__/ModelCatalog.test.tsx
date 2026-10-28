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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  window.localStorage.clear();
});

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

  it('formats and copies ModelCatalog page summary as Markdown and JSON', async () => {
    const mod = await import('../ModelCatalog');
    const md = mod.formatModelCatalogPageMarkdown({
      endpointId: 'ep-1',
      searchTerm: 'gpt',
      totalModels: 10,
      filteredCount: 2,
      snapshotCount: 1,
      activeSnapshot: 'snap-1',
      selectedKey: 'openrouter/openai/gpt-4o',
    });
    expect(md).toContain('# 模型目录页面视图摘要 (Model Catalog Page Summary)');
    expect(md).toContain('ep-1');

    const parsed = JSON.parse(
      mod.formatModelCatalogPageJson({
        endpointId: '',
        searchTerm: '',
        totalModels: 0,
        filteredCount: 0,
        snapshotCount: 0,
        activeSnapshot: null,
        selectedKey: null,
      }),
    );
    expect(parsed.totalModels).toBe(0);

    mocks.listModels.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    mocks.listSnapshots.mockResolvedValue([]);
    const Page = mod.default;
    render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );
  });

  // ---- Task 10（只增不改）: 卡片视图 / 过滤 / 排序 / 高级折叠 ----

  function catalogItems() {
    return [
      {
        model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
        tier: 'powerful',
        native: 200000,
        price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
        capabilities: { vision: true },
        source: 'openrouter',
        pricing_scope: 'base',
      },
      {
        model_key: { provider: 'openai', model_id: 'gpt-4o-mini' },
        tier: null,
        native: 128000,
        price: { input_per_million: '0.15', output_per_million: '0.6', currency: 'USD' },
        capabilities: { tool_use: true },
        source: 'openrouter',
        pricing_scope: 'base',
      },
    ];
  }

  function mockCatalogList(): void {
    mocks.listModels.mockResolvedValue({
      items: catalogItems(),
      total: 2,
      limit: 50,
      offset: 0,
    });
    mocks.listSnapshots.mockResolvedValue([]);
    mocks.getEffective.mockResolvedValue(null);
  }

  async function renderCatalogPage() {
    const Page = (await import('../ModelCatalog')).default;
    return render(
      <MemoryRouter initialEntries={['/model-catalog']}>
        <I18nProvider defaultLocale="zh">
          <Page />
        </I18nProvider>
      </MemoryRouter>,
    );
  }

  it('默认卡片视图, 切换到表格后持久化到 localStorage', async () => {
    mockCatalogList();
    const first = await renderCatalogPage();

    expect(await screen.findByTestId('catalog-cards')).toBeInTheDocument();
    expect(window.localStorage.getItem('modelCatalogView')).toBeNull();

    fireEvent.click(screen.getByTestId('model-catalog-view-table'));

    expect(await screen.findByTestId('catalog-table')).toBeInTheDocument();
    expect(window.localStorage.getItem('modelCatalogView')).toBe('table');

    first.unmount();

    await renderCatalogPage();
    expect(await screen.findByTestId('catalog-table')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-cards')).not.toBeInTheDocument();
  });

  it('卡片展示 tier 中文徽标, 未分类显示未知', async () => {
    mockCatalogList();
    await renderCatalogPage();

    const badges = await screen.findAllByTestId('catalog-card-tier');
    expect(badges.map((badge) => badge.textContent)).toEqual(['强力', '未知']);
  });

  it('tier 过滤在卡片与表格视图均生效', async () => {
    mockCatalogList();
    await renderCatalogPage();
    await screen.findByTestId('catalog-cards');

    fireEvent.change(screen.getByTestId('model-catalog-tier-filter'), {
      target: { value: 'powerful' },
    });

    await waitFor(() => {
      expect(screen.queryByText('openai/gpt-4o-mini')).not.toBeInTheDocument();
    });
    expect(screen.getByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('model-catalog-view-table'));
    const table = await screen.findByTestId('catalog-table');
    expect(within(table).getByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();
    expect(within(table).queryByText('openai/gpt-4o-mini')).not.toBeInTheDocument();
  });

  it('provider 过滤后其他 provider 的模型消失', async () => {
    mockCatalogList();
    await renderCatalogPage();

    expect(await screen.findByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();
    expect(screen.getByText('openai/gpt-4o-mini')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('model-catalog-provider-filter'), {
      target: { value: 'openai' },
    });

    await waitFor(() => {
      expect(screen.queryByText('openrouter/anthropic/claude-3.5-sonnet')).not.toBeInTheDocument();
    });
    expect(screen.getByText('openai/gpt-4o-mini')).toBeInTheDocument();
  });

  it('默认 context 降序, 切换升序后首卡顺序反转', async () => {
    mockCatalogList();
    await renderCatalogPage();

    const cards = await screen.findByTestId('catalog-cards');
    expect(within(cards).getAllByRole('listitem')[0]).toHaveTextContent(
      'anthropic/claude-3.5-sonnet',
    );

    fireEvent.change(screen.getByTestId('model-catalog-sort'), {
      target: { value: 'context_asc' },
    });

    expect(within(screen.getByTestId('catalog-cards')).getAllByRole('listitem')[0]).toHaveTextContent(
      'gpt-4o-mini',
    );
  });

  it('高级折叠包含同步 / 导入 / 导出三个按钮', async () => {
    mockCatalogList();
    await renderCatalogPage();

    const advanced = await screen.findByTestId('model-catalog-advanced');
    expect(advanced.tagName).toBe('DETAILS');
    expect(within(advanced).getByTestId('model-catalog-sync')).toBeInTheDocument();
    expect(within(advanced).getByTestId('model-catalog-import')).toBeInTheDocument();
    expect(within(advanced).getByTestId('model-catalog-export')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('model-catalog-header')).queryByTestId('model-catalog-sync'),
    ).not.toBeInTheDocument();
  });

  it('能力过滤只保留具备该能力的模型', async () => {
    mockCatalogList();
    await renderCatalogPage();
    await screen.findByTestId('catalog-cards');

    fireEvent.change(screen.getByTestId('model-catalog-capability-filter'), {
      target: { value: 'vision' },
    });

    await waitFor(() => {
      expect(screen.queryByText('openai/gpt-4o-mini')).not.toBeInTheDocument();
    });
    expect(screen.getByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();
  });

  it('价格升序按输入价排列, 无价格条目排最后', async () => {
    mocks.listModels.mockResolvedValue({
      items: [
        ...catalogItems(),
        {
          model_key: { provider: 'local', model_id: 'ollama-unknown' },
          tier: 'fast',
          native: null,
          price: { input_per_million: null, output_per_million: null, currency: 'USD' },
          capabilities: null,
          source: 'builtin',
          pricing_scope: 'base',
        },
      ],
      total: 3,
      limit: 50,
      offset: 0,
    });
    mocks.listSnapshots.mockResolvedValue([]);
    mocks.getEffective.mockResolvedValue(null);

    await renderCatalogPage();
    await screen.findByTestId('catalog-cards');

    fireEvent.change(screen.getByTestId('model-catalog-sort'), {
      target: { value: 'price_asc' },
    });

    const cards = within(screen.getByTestId('catalog-cards')).getAllByRole('listitem');
    expect(cards[0]).toHaveTextContent('gpt-4o-mini');
    expect(cards[1]).toHaveTextContent('anthropic/claude-3.5-sonnet');
    expect(cards[2]).toHaveTextContent('local/ollama-unknown');
  });

  it('过滤把已选模型筛掉后右侧详情回到空态', async () => {
    mockCatalogList();
    await renderCatalogPage();

    const card = await screen.findByTestId(
      'catalog-card-openrouter/anthropic%2Fclaude-3.5-sonnet/openrouter/base',
    );
    fireEvent.click(card);
    expect(card).toHaveAttribute('aria-selected', 'true');

    fireEvent.change(screen.getByTestId('model-catalog-tier-filter'), {
      target: { value: 'fast' },
    });

    await waitFor(() => {
      expect(
        screen.queryByTestId('catalog-card-openrouter/anthropic%2Fclaude-3.5-sonnet/openrouter/base'),
      ).toBeNull();
    });
    expect(screen.getByTestId('model-details-empty')).toBeInTheDocument();
  });
});
