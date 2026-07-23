import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { settingsClient } from '../../../shared/api/settingsClient';
import { loadSettings } from '../storage';
import { DEFAULT_SETTINGS } from '../types';

vi.mock('../../../shared/api/settingsClient');

describe('loadSettings', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('remote null + local null → DEFAULT_SETTINGS', async () => {
    vi.mocked(settingsClient.getSettings).mockResolvedValue(null);
    const result = await loadSettings();
    expect(result).toEqual(DEFAULT_SETTINGS);
  });

  it('remote 完整 camelCase, local 空 → 返回 remote', async () => {
    const remote = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: 'n',
          baseUrl: 'u',
          apiKey: 'k',
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.endpoints[0].baseUrl).toBe('u');
  });

  it('remote null + local 有 → 返回 local', async () => {
    vi.mocked(settingsClient.getSettings).mockResolvedValue(null);
    localStorage.setItem(
      'sage-settings',
      JSON.stringify({
        streaming: true,
        endpoints: [],
        modelSelections: {
          chatModel: { endpointId: 'e1', modelId: 'm1' },
          visionModel: { endpointId: null, modelId: null },
          embeddingModel: { endpointId: null, modelId: null },
        },
      }),
    );
    const result = await loadSettings();
    expect(result.modelSelections.chatModel.endpointId).toBe('e1');
  });

  it('local + remote 都存在 → deepMerge 字段级合并 + writeLocalCacheSync', async () => {
    const local = {
      ...DEFAULT_SETTINGS,
      streaming: false,
      endpoints: [
        {
          id: 'e1',
          name: 'local',
          baseUrl: 'local-url',
          apiKey: 'local-key',
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    localStorage.setItem('sage-settings', JSON.stringify(local));

    const remote = { ...DEFAULT_SETTINGS, streaming: true, endpoints: [] };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.streaming).toBe(true);
    expect(result.endpoints).toHaveLength(1);
    expect(result.endpoints[0].baseUrl).toBe('local-url');

    const cached = JSON.parse(localStorage.getItem('sage-settings')!);
    expect(cached.streaming).toBe(true);
    expect(cached.endpoints[0].baseUrl).toBe('local-url');
  });
});
