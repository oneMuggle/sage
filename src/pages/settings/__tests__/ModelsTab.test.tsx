// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type ModelCapability } from '../../../entities/setting/types';
import {
  formatModelsTabAuditJson,
  formatModelsTabAuditSnapshot,
  ModelsTab,
} from '../ModelsTab';

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

  it('uses the corrected Temperature description', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(screen.getByText(/0 最稳定，2 最随机/)).toBeInTheDocument();
  });

  it('exports ModelsTab audit snapshot and JSON helpers and renders copy controls', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(screen.getByTestId('models-tab-copy-audit')).toBeInTheDocument();
    expect(screen.getByTestId('models-tab-copy-json')).toBeInTheDocument();

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
