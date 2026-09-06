// src/widgets/chat/__tests__/SessionModelPicker.test.tsx
// U8 会话级模型切换组件测试 — sessionApi / useSettings 全 mock。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SessionModelPicker } from '../SessionModelPicker';

const mockGetModelOverride = vi.fn<() => Promise<string | null>>();
const mockSetModelOverride = vi.fn<(sessionId: string, model: string) => Promise<string | null>>();

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
