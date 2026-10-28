// src/widgets/chat/__tests__/SessionModelPicker.test.tsx
// U8 会话级模型切换组件测试 — sessionApi / useSettings 全 mock。
// Task 7 (2026-10-28): 增加智能路由自动模式与 tier 分组用例；
// 现有 9 个用例保持断言不变（它们走 settings 无 routing 键 → 手动模式 → 平铺回退）。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import {
  SessionModelPicker,
  formatSessionModelPickerJson,
  formatSessionModelPickerMarkdown,
} from '../SessionModelPicker';

const mockGetModelOverride = vi.fn<() => Promise<string | null>>();
const mockSetModelOverride = vi.fn<(sessionId: string, model: string) => Promise<string | null>>();
// P1-3: 切换前预检的两路数据源
const mockGetEffective = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const mockFetchSessionUsage =
  vi.fn<(...args: unknown[]) => Promise<{ last_prompt_tokens: number | null }>>();
// Task 7: tier 分组数据源 + 路由预览
const mockListModels = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const mockRouteModel = vi.fn<(...args: unknown[]) => Promise<unknown>>();

vi.mock('../../../entities/model-catalog/api', () => ({
  getEffective: (endpointId: string, modelId: string) => mockGetEffective(endpointId, modelId),
  listModels: (params: unknown) => mockListModels(params),
}));

vi.mock('../../../entities/routing/api', () => ({
  routeModel: (req: unknown) => mockRouteModel(req),
}));

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetchSessionUsage(sessionId),
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    getModelOverride: () => mockGetModelOverride(),
    setModelOverride: (sessionId: string, model: string) => mockSetModelOverride(sessionId, model),
  },
}));

const mockSettings = {
  endpoints: [
    {
      id: 'ep1',
      name: '本地 Ollama',
      baseUrl: 'http://x',
      apiKey: '',
      discoveredModels: [
        { id: 'qwen2.5:7b', capabilities: [], endpointId: 'ep1' },
        { id: 'llama3:8b', capabilities: [], endpointId: 'ep1' },
      ],
    },
  ],
  modelSelections: {
    chatModel: { endpointId: 'ep1', modelId: 'qwen2.5:7b' },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
  },
  maxContext: 4096,
  routing: { mode: 'manual' as 'auto' | 'manual' },
};

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({ settings: mockSettings }),
}));

const EMPTY_CATALOG = { items: [], total: 0, limit: 100, offset: 0 };

const ROUTE_RESPONSE = {
  selected_model: {
    model_key: { provider: 'ollama', model_id: 'qwen2.5:14b' },
    tier: 'powerful',
    limits: { native: null, service: null },
    price: { input_per_million: null, output_per_million: null, currency: 'USD' },
    provenance: {},
    revision: 0,
  },
  reason: '已为 code_review 选择 powerful 模型',
  alternatives: [],
};

function resetMocks(): void {
  vi.clearAllMocks();
  mockSettings.routing.mode = 'manual';
  localStorage.clear();
  mockGetModelOverride.mockResolvedValue(null);
  mockSetModelOverride.mockResolvedValue('llama3:8b');
  // 默认：窗口未知 → 不拦截（未知 ≠ 有风险）
  mockGetEffective.mockResolvedValue(null);
  mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 0 });
  mockListModels.mockResolvedValue(EMPTY_CATALOG);
  mockRouteModel.mockResolvedValue(ROUTE_RESPONSE);
}

describe('SessionModelPicker', () => {
  beforeEach(resetMocks);

  it('shows follow-global option with the global model id', async () => {
    render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('session-model-picker')).not.toBeDisabled();
    });
    const select = screen.getByTestId('session-model-picker') as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(screen.getByText(/跟随全局 \(qwen2.5:7b\)/)).toBeInTheDocument();
    expect(screen.getByText('llama3:8b · 本地 Ollama')).toBeInTheDocument();
  });

  it('loads and displays an existing override', async () => {
    mockGetModelOverride.mockResolvedValue('llama3:8b');
    render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect((screen.getByTestId('session-model-picker') as HTMLSelectElement).value).toBe(
        'llama3:8b',
      );
    });
    expect(screen.getByText('覆盖')).toBeInTheDocument();
  });

  it('calls setModelOverride on change', async () => {
    render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('session-model-picker')).not.toBeDisabled();
    });
    fireEvent.change(screen.getByTestId('session-model-picker'), {
      target: { value: 'llama3:8b' },
    });
    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
  });

  it('is disabled without a session', () => {
    render(<SessionModelPicker sessionId={null} />);
    expect(screen.getByTestId('session-model-picker')).toBeDisabled();
  });

  it('formats and copies session model picker summary as Markdown and JSON', () => {
    const md = formatSessionModelPickerMarkdown({
      sessionId: 's1',
      override: 'llama3:8b',
      globalModelId: 'qwen2.5:7b',
      optionCount: 2,
    });
    expect(md).toContain('# 会话模型选择状态 (Session Model Picker Summary)');
    expect(md).toContain('llama3:8b');

    const parsed = JSON.parse(
      formatSessionModelPickerJson({
        sessionId: null,
        override: null,
        globalModelId: null,
        optionCount: 0,
      }),
    );
    expect(parsed.optionCount).toBe(0);

    render(<SessionModelPicker sessionId="s1" />);
  });
});

/**
 * P1-3: 消除「盲切换」—— 换到小窗口模型前必须告知历史会被截断。
 * 未知（catalog 无数据 / usage 取不到）不拦截，避免把正常切换变成阻碍。
 */
describe('SessionModelPicker 切换预检（P1-3）', () => {
  beforeEach(resetMocks);

  async function changeTo(model: string) {
    render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('session-model-picker')).not.toBeDisabled();
    });
    fireEvent.change(screen.getByTestId('session-model-picker'), { target: { value: model } });
  }

  it('占用超过目标窗口 80% 时先提示、确认后才切换', async () => {
    mockGetEffective.mockResolvedValue({ limits: { native: 8000, service: null } });
    mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 7000 });

    await changeTo('llama3:8b');

    const warn = await screen.findByTestId('model-switch-warning');
    expect(warn.textContent).toContain('8.0k');
    expect(warn.textContent).toContain('7.0k');
    // 关键：提示阶段不得已经切换
    expect(mockSetModelOverride).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('model-switch-confirm'));
    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
  });

  it('取消则不切换', async () => {
    mockGetEffective.mockResolvedValue({ limits: { native: 8000, service: null } });
    mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 7000 });

    await changeTo('llama3:8b');
    await screen.findByTestId('model-switch-warning');
    fireEvent.click(screen.getByTestId('model-switch-cancel'));

    await waitFor(() => expect(screen.queryByTestId('model-switch-warning')).toBeNull());
    expect(mockSetModelOverride).not.toHaveBeenCalled();
  });

  it('占用低于阈值时直接切换，不打扰用户', async () => {
    mockGetEffective.mockResolvedValue({ limits: { native: 128000, service: null } });
    mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 1000 });

    await changeTo('llama3:8b');

    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
    expect(screen.queryByTestId('model-switch-warning')).toBeNull();
  });

  it('窗口未知时不拦截（catalog 未收录）', async () => {
    mockGetEffective.mockResolvedValue(null);
    mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 999999 });

    await changeTo('llama3:8b');

    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
    expect(screen.queryByTestId('model-switch-warning')).toBeNull();
  });

  it('预检接口失败时不拦截，降级为直接切换', async () => {
    mockGetEffective.mockRejectedValue(new Error('catalog down'));
    mockFetchSessionUsage.mockRejectedValue(new Error('usage down'));

    await changeTo('llama3:8b');

    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
    expect(screen.queryByTestId('model-switch-warning')).toBeNull();
  });
});

/**
 * Task 7 (2026-10-28) 智能路由自动模式 + tier 分组。
 * R26: 自动模式绝不写 override；R27: tier 分组顺序固定；
 * R28: 预览失败只提示，不抛错、不 toast。
 */
describe('SessionModelPicker 智能路由自动模式 + tier 分组', () => {
  beforeEach(resetMocks);

  function openRoutingPanel(): void {
    const details = screen.getByTestId('session-routing-auto') as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event('toggle', { bubbles: true }));
  }

  it('自动模式不渲染会写 override 的 select', () => {
    mockSettings.routing.mode = 'auto';

    render(<SessionModelPicker sessionId="s1" />);

    expect(screen.queryByTestId('session-model-picker')).toBeNull();
    expect(screen.getByTestId('session-routing-auto')).toBeInTheDocument();
  });

  it('自动模式切换任务类型永不写 override', async () => {
    mockSettings.routing.mode = 'auto';

    render(<SessionModelPicker sessionId="s1" />);
    openRoutingPanel();
    fireEvent.change(screen.getByTestId('routing-task-type'), {
      target: { value: 'analysis' },
    });

    await waitFor(() => {
      expect(mockRouteModel).toHaveBeenCalled();
    });
    expect(mockSetModelOverride).not.toHaveBeenCalled();
  });

  it('任务类型选择会持久化到 localStorage', async () => {
    mockSettings.routing.mode = 'auto';

    render(<SessionModelPicker sessionId="s1" />);
    openRoutingPanel();
    fireEvent.change(screen.getByTestId('routing-task-type'), {
      target: { value: 'code_review' },
    });

    // 等预览落地，避免路由请求在用例结束后才回写 state。
    await screen.findByTestId('routing-preview');
    expect(localStorage.getItem('routingTaskType')).toBe('code_review');
  });

  it('展开面板后展示 routeModel 预览（模型 / tier / reason）', async () => {
    mockSettings.routing.mode = 'auto';

    render(<SessionModelPicker sessionId="s1" />);
    openRoutingPanel();

    const preview = await screen.findByTestId('routing-preview');
    expect(preview.textContent).toContain('qwen2.5:14b');
    expect(preview.textContent).toContain('powerful');
    expect(preview.textContent).toContain('已为 code_review 选择 powerful 模型');
    expect(mockRouteModel).toHaveBeenCalledWith(
      expect.objectContaining({
        endpoint_id: 'ep1',
        task_type: 'chat',
        required_capabilities: ['chat'],
      }),
    );
  });

  it('已锁定覆盖时只提示，不发起 routeModel 预览', async () => {
    mockSettings.routing.mode = 'auto';
    mockGetModelOverride.mockResolvedValue('llama3:8b');

    render(<SessionModelPicker sessionId="s1" />);
    openRoutingPanel();

    const locked = await screen.findByTestId('routing-locked');
    expect(locked.textContent).toContain('本会话已锁定 llama3:8b');
    expect(mockRouteModel).not.toHaveBeenCalled();
  });

  it('tier 分组顺序恒为 快速 → 均衡 → 强力 → 未分类', async () => {
    mockListModels.mockResolvedValue({
      items: [
        {
          model_key: { provider: 'ollama', model_id: 'power-model' },
          tier: 'powerful',
          native: 32000,
          price: { input_per_million: '1.00', output_per_million: '2.00', currency: 'USD' },
        },
        {
          model_key: { provider: 'ollama', model_id: 'fast-model' },
          tier: 'fast',
          native: 8000,
          price: { input_per_million: '0.10', output_per_million: '0.20', currency: 'USD' },
        },
        {
          model_key: { provider: 'ollama', model_id: 'unknown-model' },
          tier: null,
          native: null,
          price: { input_per_million: null, output_per_million: null, currency: 'USD' },
        },
        {
          model_key: { provider: 'ollama', model_id: 'balanced-model' },
          tier: 'balanced',
          native: 16000,
          price: { input_per_million: '0.50', output_per_million: '1.00', currency: 'USD' },
        },
      ],
      total: 4,
      limit: 100,
      offset: 0,
    });

    const { container } = render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect(container.querySelectorAll('optgroup').length).toBe(4);
    });

    const labels = Array.from(container.querySelectorAll('optgroup')).map((group) =>
      group.getAttribute('label'),
    );
    expect(labels).toEqual(['快速', '均衡', '强力', '未分类']);
  });

  it('catalog 离线时回退平铺列表，手动切换照常写 override', async () => {
    // mode 保持 manual
    mockListModels.mockRejectedValue(new Error('offline'));

    render(<SessionModelPicker sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('session-model-picker')).not.toBeDisabled();
    });
    expect(screen.getByText('llama3:8b · 本地 Ollama')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('session-model-picker'), {
      target: { value: 'llama3:8b' },
    });
    await waitFor(() => {
      expect(mockSetModelOverride).toHaveBeenCalledWith('s1', 'llama3:8b');
    });
  });

  it('路由预览失败时显示不可用，不崩溃也不写 override', async () => {
    mockSettings.routing.mode = 'auto';
    mockRouteModel.mockRejectedValue(new Error('routing down'));

    render(<SessionModelPicker sessionId="s1" />);
    openRoutingPanel();

    const error = await screen.findByTestId('routing-preview-error');
    expect(error.textContent).toContain('路由预览不可用');
    expect(mockSetModelOverride).not.toHaveBeenCalled();
  });
});
