import { describe, expect, it, vi } from 'vitest';

import { deepMerge } from '../deepMerge';
import type { AppSettings } from '../types';
import { DEFAULT_SETTINGS } from '../types';

const remoteClean: AppSettings = {
  ...DEFAULT_SETTINGS,
  endpoints: [
    {
      id: 'e1',
      name: '新端点',
      baseUrl: 'https://example.com/v1',
      apiKey: 'sk-remote',
      discoveredModels: [
        {
          id: 'm1',
          capabilities: ['chat'],
          endpointId: 'e1',
        },
      ],
      lastDiscoveredAt: 1000,
    },
  ],
  modelSelections: {
    chatModel: { endpointId: 'e1', modelId: 'm1' },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
  },
};

const localClean: AppSettings = {
  ...DEFAULT_SETTINGS,
  streaming: false,
};

describe('deepMerge', () => {
  it('remote 仅 (无 local) → 直接返回 remote', () => {
    expect(deepMerge(remoteClean, null)).toEqual(remoteClean);
  });

  it('local 仅 (无 remote) → 直接返回 local', () => {
    expect(deepMerge(null, localClean)).toEqual(localClean);
  });

  it('字段级合并: local.streaming=false + remote.streaming=true → remote wins', () => {
    const merged = deepMerge(localClean, remoteClean);
    expect(merged.streaming).toBe(true);
  });

  it('endpoints[] 按 id 去重: 同 id 走字段比较, remote 胜', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: '老端点',
          baseUrl: 'https://old.com',
          apiKey: 'sk-old',
          discoveredModels: [],
          lastDiscoveredAt: 0,
        },
      ],
    };
    const merged = deepMerge(local, remoteClean);
    expect(merged.endpoints).toHaveLength(1);
    expect(merged.endpoints[0].baseUrl).toBe('https://example.com/v1');
  });

  it('同 id 不同 baseUrl → console.warn + remote 胜', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'e1',
          name: '老端点',
          baseUrl: 'https://old.com',
          apiKey: 'sk-old',
          discoveredModels: [],
          lastDiscoveredAt: 0,
        },
      ],
    };
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    deepMerge(local, remoteClean);
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/conflict on 'endpoints\[e1\]\.baseUrl'/),
    );
    warn.mockRestore();
  });

  it('嵌套 objects 字段级递归: modelSelections.chatModel 各字段按规则', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      modelSelections: {
        chatModel: { endpointId: 'e1', modelId: 'm-LOCAL' },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
    };
    const merged = deepMerge(local, remoteClean);
    expect(merged.modelSelections.chatModel.endpointId).toBe('e1');
    expect(merged.modelSelections.chatModel.modelId).toBe('m1');
  });

  it('叶节点 (string/number/boolean) → override 完全替换 base', () => {
    const merged = deepMerge(
      { a: 'local' as const, b: 1, c: true },
      { a: 'remote' as const, b: 2, c: false },
    );
    expect(merged).toEqual({ a: 'remote', b: 2, c: false });
  });

  it('endpoints[] remote 完全空数组 → 不应污染 local', () => {
    const local: AppSettings = {
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
    const remoteEmpty: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [],
    };
    const merged = deepMerge(local, remoteEmpty);
    expect(merged.endpoints).toHaveLength(1);
  });
});

describe('deepMerge security (fix/security-perf-quickwins)', () => {
  it('__proto__ 键被 denylist 过滤, 不能污染 Object.prototype', () => {
    const malicious = JSON.parse('{"__proto__":{"polluted":true}}');
    const merged = deepMerge<Record<string, unknown>>({}, malicious as Record<string, unknown>);
    // 合并结果不含 __proto__ 字段
    expect(Object.keys(merged)).not.toContain('__proto__');
    // Object.prototype 未被污染
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('constructor 键被 denylist 过滤', () => {
    const malicious = JSON.parse('{"constructor":{"prototype":{"polluted":true}}}');
    const merged = deepMerge<Record<string, unknown>>({}, malicious as Record<string, unknown>);
    expect(Object.keys(merged)).not.toContain('constructor');
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('apiKey 字段冲突时 console.warn 不泄漏密钥明文', () => {
    const local = { endpoints: [{ id: 'e1', apiKey: 'sk-LOCAL-SECRET' }] };
    const remote = { endpoints: [{ id: 'e1', apiKey: 'sk-REMOTE-SECRET' }] };
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    deepMerge(local, remote);
    expect(warn).toHaveBeenCalledTimes(1);
    const message = warn.mock.calls[0]?.[0] ?? '';
    expect(message).toMatch(/conflict on 'endpoints\[e1\]\.apiKey'/);
    expect(message).not.toContain('sk-LOCAL-SECRET');
    expect(message).not.toContain('sk-REMOTE-SECRET');
    expect(message).toContain('<redacted>');
    warn.mockRestore();
  });

  it('非敏感字段冲突时仍打印明文（行为不变）', () => {
    const local = { endpoints: [{ id: 'e1', baseUrl: 'https://old.com' }] };
    const remote = { endpoints: [{ id: 'e1', baseUrl: 'https://new.com' }] };
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    deepMerge(local, remote);
    expect(warn).toHaveBeenCalledTimes(1);
    const message = warn.mock.calls[0]?.[0] ?? '';
    expect(message).toContain('https://old.com');
    expect(message).toContain('https://new.com');
    warn.mockRestore();
  });
});
