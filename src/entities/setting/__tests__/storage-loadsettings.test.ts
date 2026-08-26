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

  it('2026-08-26: 脱敏 GET (apiKey="" + hasApiKey=true) 不能覆盖本地真实 apiKey', async () => {
    // 后端 redact_secrets 把真实 key 替换为 "" + 加 hasApiKey=true 标志. 若
    // 客户端不做特例, deepMerge remote-wins 策略会把 local.apiKey='sk-LOCAL-REAL'
    // 替换为 '', 用户每次启动都会丢 key. plan §1: 同步保留已有设置的 API key.
    const local = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: 'LM Studio',
          baseUrl: 'http://127.0.0.1:1234/v1',
          apiKey: 'sk-LOCAL-REAL',
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    localStorage.setItem('sage-settings', JSON.stringify(local));

    const remote = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: 'LM Studio',
          baseUrl: 'http://127.0.0.1:1234/v1',
          // 脱敏 GET 的精确形态: apiKey 字段为空字符串, hasApiKey=true 标志.
          apiKey: '',
          hasApiKey: true,
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.endpoints).toHaveLength(1);
    expect(result.endpoints[0].apiKey).toBe('sk-LOCAL-REAL');

    // 写入缓存的也必须是真实 key, 否则下次启动依然空 → key 永久丢失.
    const cached = JSON.parse(localStorage.getItem('sage-settings')!);
    expect(cached.endpoints[0].apiKey).toBe('sk-LOCAL-REAL');
  });

  it('2026-08-26: 脱敏 GET (apiKey="" + hasApiKey=false) → 用户从未设置 key, 保留空', async () => {
    // hasApiKey=false 表示后端确认该字段空 (e.g. 用户新建 endpoint 留空). 不应
    // 从 local 兜底凭空捏造 key.
    const local = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: 'no-key',
          baseUrl: 'http://localhost',
          apiKey: '',
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    localStorage.setItem('sage-settings', JSON.stringify(local));

    const remote = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: 'no-key',
          baseUrl: 'http://localhost',
          apiKey: '',
          hasApiKey: false,
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
    };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.endpoints[0].apiKey).toBe('');
  });
});
