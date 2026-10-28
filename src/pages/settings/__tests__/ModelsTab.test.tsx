// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type ModelCapability } from '../../../entities/setting/types';
import { formatModelsTabAuditJson, formatModelsTabAuditSnapshot, ModelsTab } from '../ModelsTab';

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));

const settings = {
  ...DEFAULT_SETTINGS,
  endpoints: [
    {
      id: 'ep-1',
      name: 'Test',
      baseUrl: 'http://localhost',
      apiKey: '',
      protocol: 'openai-compatible' as const,
      modelId: '',
      localModelPath: '',
      discoveredModels: [
        { id: 'model-1', capabilities: ['chat'] as ModelCapability[], endpointId: 'ep-1' },
      ],
      lastDiscoveredAt: null,
    },
  ],
  modelSelections: {
    chatModel: { endpointId: 'ep-1', modelId: 'model-1' },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
    ttsModel: { endpointId: null, modelId: null },
    asrModel: { endpointId: null, modelId: null },
    imageGenModel: { endpointId: null, modelId: null },
  },
  maxContext: 4096,
  autoContext: true,
  temperature: 0.7,
};

describe('ModelsTab context controls', () => {
  it('disables the fixed context input in automatic mode', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(screen.getByTestId('settings-max-context')).toBeDisabled();
  });

  it('renders max output tokens and writes it back on change', () => {
    const updateSettings = vi.fn();
    render(<ModelsTab settings={settings} updateSettings={updateSettings} />);

    const input = screen.getByTestId('settings-max-output-tokens');
    expect(input).toHaveValue(4096);
    expect(input).toHaveAttribute('min', '512');
    expect(input).toHaveAttribute('max', '32768');

    fireEvent.change(input, { target: { value: '8192' } });
    expect(updateSettings).toHaveBeenCalledWith({ maxOutputTokens: 8192 });
  });

  it('uses the corrected Temperature description', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(screen.getByText(/0 最稳定，2 最随机/)).toBeInTheDocument();
  });

  it('exports ModelsTab audit snapshot and JSON helpers and renders copy controls', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(screen.getByTestId('models-tab-copy-audit')).toBeInTheDocument();

    const snapshot = formatModelsTabAuditSnapshot({
      endpointCount: 1,
      discoveredModelCount: 3,
      chatModel: 'model-1',
      visionModel: null,
      embeddingModel: 'emb-1',
      maxContext: 4096,
      autoContext: true,
      temperature: 0.7,
    });
    expect(snapshot).toContain('# 模型选择审计快照');
    expect(snapshot).toContain('对话模型: model-1');
    expect(snapshot).toContain('上下文模式: 自动推断');

    const json = JSON.parse(
      formatModelsTabAuditJson({
        endpointCount: 1,
        discoveredModelCount: 1,
        chatModel: 'model-1',
        visionModel: null,
        embeddingModel: null,
        maxContext: 8192,
        autoContext: false,
        temperature: 0.2,
      }),
    );
    expect(json).toEqual({
      endpointCount: 1,
      discoveredModelCount: 1,
      chatModel: 'model-1',
      visionModel: null,
      embeddingModel: null,
      maxContext: 8192,
      autoContext: false,
      temperature: 0.2,
    });
  });
});
