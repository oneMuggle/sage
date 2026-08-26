/**
 * 2026-08-26: canonical 净化单元测试.
 *
 * 覆盖：
 * - snake_case 历史残留 (memory_server_sync / local_model_path) 被剥离
 * - 已知非法字段 (memoryServerSync / localModelPath) 也被剥离
 * - 白名单内字段保留
 * - endpoints[*] 嵌套净化
 * - 不可变性 (不修改入参)
 */
import { describe, expect, it } from 'vitest';

import { __test__sanitizeForBackend, __test__SNAKE_KEYS_TO_DROP } from '../storage';
import type { AppSettings } from '../types';

type LooseSettings = Partial<AppSettings> & Record<string, unknown>;

describe('sanitizeForBackend (2026-08-26 canonical cleanup)', () => {
  it('strips memory_server_sync snake_case residue', () => {
    const out = __test__sanitizeForBackend({
      streaming: true,
      memory_server_sync: true,
    } as unknown as LooseSettings) as unknown as LooseSettings;
    expect('memory_server_sync' in out).toBe(false);
    expect(out.streaming).toBe(true);
  });

  it('strips legacy camelCase fields no longer in backend whitelist', () => {
    const out = __test__sanitizeForBackend({
      streaming: true,
      memoryServerSync: true,
    } as unknown as LooseSettings) as unknown as LooseSettings;
    expect('memoryServerSync' in out).toBe(false);
  });

  it('strips local_model_path / localModelPath inside endpoints[*]', () => {
    const out = __test__sanitizeForBackend({
      endpoints: [
        {
          id: 'ep1',
          name: 'LM Studio',
          baseUrl: 'http://127.0.0.1:1234/v1',
          apiKey: '',
          local_model_path: '/old/path',
          localModelPath: '/old/path2',
          protocol: 'openai-compatible',
        },
      ],
    } as unknown as LooseSettings) as unknown as LooseSettings;
    const ep = (out.endpoints as unknown as Record<string, unknown>[])[0];
    expect('local_model_path' in ep).toBe(false);
    expect('localModelPath' in ep).toBe(false);
    expect(ep.baseUrl).toBe('http://127.0.0.1:1234/v1');
  });

  it('preserves all whitelisted top-level and endpoint fields', () => {
    const out = __test__sanitizeForBackend({
      streaming: true,
      autoMemory: true,
      maxContext: 4096,
      temperature: 0.7,
      timezone: 'Asia/Shanghai',
      endpoints: [
        {
          id: 'ep1',
          name: 'OpenAI',
          baseUrl: 'https://api.example.com/v1',
          apiKey: 'sk-secret-NOT-LEAKING',
          protocol: 'openai-compatible',
          modelId: 'gpt-4',
          discoveredModels: [],
          lastDiscoveredAt: 0,
        },
      ],
      wiki: { useFolderPicker: true },
      version: '4.0.0',
    } as unknown as LooseSettings) as unknown as LooseSettings;
    const ep = (out.endpoints as unknown as Record<string, unknown>[])[0];
    expect(ep.apiKey).toBe('sk-secret-NOT-LEAKING');
    expect(out.streaming).toBe(true);
  });

  it('does not mutate input (immutability)', () => {
    const partial = {
      streaming: true,
      memory_server_sync: true,
      endpoints: [
        {
          id: 'ep1',
          localModelPath: '/x',
        },
      ],
    };
    const snapshot = JSON.stringify(partial);
    __test__sanitizeForBackend(partial as unknown as LooseSettings);
    expect(JSON.stringify(partial)).toBe(snapshot);
  });

  it('handles null / non-object gracefully', () => {
    const sanitizer = __test__sanitizeForBackend as unknown as (v: unknown) => unknown;
    expect(sanitizer(null)).toBeNull();
    expect(sanitizer('raw')).toBe('raw');
    expect(sanitizer(42)).toBe(42);
  });

  it('SNAKE_KEYS_TO_DROP is exported for cross-check', () => {
    expect(__test__SNAKE_KEYS_TO_DROP.has('memory_server_sync')).toBe(true);
    expect(__test__SNAKE_KEYS_TO_DROP.has('local_model_path')).toBe(true);
  });
});
