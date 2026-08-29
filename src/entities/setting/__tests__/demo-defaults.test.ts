import { describe, expect, it } from 'vitest';

import { DEFAULT_SETTINGS, DEMO_ENDPOINT_ID, withDemoSettingsDefaults } from '../types';

function makeEndpoint(id: string, baseUrl: string) {
  return {
    id,
    name: id,
    baseUrl,
    apiKey: '',
    protocol: 'openai-compatible' as const,
    modelId: '',
    localModelPath: '',
    discoveredModels: [],
    lastDiscoveredAt: null,
  };
}

describe('withDemoSettingsDefaults', () => {
  it('adds a usable endpoint and model selections to empty settings', () => {
    const result = withDemoSettingsDefaults({ ...DEFAULT_SETTINGS });

    expect(result.demoMode).toBe(true);
    expect(result.endpoints).toHaveLength(1);
    expect(result.endpoints[0]).toMatchObject({
      id: DEMO_ENDPOINT_ID,
      baseUrl: 'http://127.0.0.1:1234/v1',
    });
    expect(result.modelSelections.chatModel).toEqual({
      endpointId: DEMO_ENDPOINT_ID,
      modelId: 'qwen2.5-14b-instruct',
    });
  });

  it('repairs selections that point at missing or unusable endpoints', () => {
    const settings = {
      ...DEFAULT_SETTINGS,
      endpoints: [makeEndpoint('empty-endpoint', '')],
      modelSelections: {
        ...DEFAULT_SETTINGS.modelSelections,
        chatModel: { endpointId: 'missing', modelId: 'old-model' },
      },
    };

    const result = withDemoSettingsDefaults(settings);

    expect(result.modelSelections.chatModel).toEqual({
      endpointId: DEMO_ENDPOINT_ID,
      modelId: 'qwen2.5-14b-instruct',
    });
  });

  it('preserves valid configured endpoint selections without mutating input', () => {
    const endpoint = makeEndpoint('configured', 'https://example.test/v1');
    const settings = {
      ...DEFAULT_SETTINGS,
      endpoints: [endpoint],
      modelSelections: {
        ...DEFAULT_SETTINGS.modelSelections,
        chatModel: { endpointId: 'configured', modelId: 'custom-model' },
      },
    };

    const result = withDemoSettingsDefaults(settings);

    expect(result.modelSelections.chatModel).toEqual({
      endpointId: 'configured',
      modelId: 'custom-model',
    });
    expect(settings.modelSelections.chatModel).toEqual({
      endpointId: 'configured',
      modelId: 'custom-model',
    });
  });
});
