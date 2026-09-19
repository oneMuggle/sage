// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ModelsTab } from '../ModelsTab';
import { DEFAULT_SETTINGS, type ModelCapability } from '../../../entities/setting/types';

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
});
