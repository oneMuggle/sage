// src/widgets/chat/__tests__/SessionModelPicker.test.tsx
// U8 会话级模型切换组件测试 — sessionApi / useSettings 全 mock。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SessionModelPicker } from '../SessionModelPicker';

const mockGetModelOverride = vi.fn<() => Promise<string | null>>();
const mockSetModelOverride = vi.fn<(sessionId: string, model: string) => Promise<string | null>>();
// P1-3: 切换前预检的两路数据源
const mockGetEffective = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const mockFetchSessionUsage = vi.fn<(...args: unknown[]) => Promise<{ last_prompt_tokens: number | null }>>();

vi.mock('../../../entities/model-catalog/api', () => ({
  getEffective: (endpointId: string, modelId: string) => mockGetEffective(endpointId, modelId),
}));

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetchSessionUsage(sessionId),
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    getModelOverride: () => mockGetModelOverride(),
    setModelOverride: (sessionId: string, model: string) =>
      mockSetModelOverride(sessionId, model),
  },
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
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
    },
  }),
}));

describe('SessionModelPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetModelOverride.mockResolvedValue(null);
    mockSetModelOverride.mockResolvedValue('llama3:8b');
    // 默认：窗口未知 → 不拦截（未知 ≠ 有风险）
    mockGetEffective.mockResolvedValue(null);
    mockFetchSessionUsage.mockResolvedValue({ last_prompt_tokens: 0 });
  });

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
});

/**
 * P1-3: 消除「盲切换」—— 换到小窗口模型前必须告知历史会被截断。
 * 未知（catalog 无数据 / usage 取不到）不拦截，避免把正常切换变成阻碍。
 */
describe('SessionModelPicker 切换预检（P1-3）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetModelOverride.mockResolvedValue(null);
    mockSetModelOverride.mockResolvedValue('llama3:8b');
  });

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
