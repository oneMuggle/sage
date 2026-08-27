import { describe, it, expect } from 'vitest';

import { restoreRedactedApiKeys } from '../storage';
import type { AppSettings } from '../types';
import { DEFAULT_SETTINGS } from '../types';

/**
 * alpha.8 (2026-08-27): regression for the
 * "[[sage-settings-redaction-key-preservation]] + [[sage-settings-redaction-idempotency-fix]]"
 * contract on the frontend.
 *
 * Backend GET /settings now returns redacted apiKey (empty string) + a
 * ``hasApiKey: bool`` boolean. The frontend must NOT trust the empty
 * ``apiKey`` from the backend — it must restore the real local key from
 * localStorage when ``hasApiKey === true``.
 *
 * ``restoreRedactedApiKeys`` is the pure-function part of that contract.
 * ``loadSettings`` calls it after ``deepMerge(local, remote, 'remote-wins')``
 * to fix-up the endpoints[*].apiKey fields.
 */

const fullEndpoint = (overrides: Partial<AppSettings['endpoints'][number]> = {}) => ({
  id: 'e1',
  name: 'LM Studio',
  baseUrl: 'http://127.0.0.1:1234/v1',
  apiKey: '',
  protocol: 'openai-compatible' as const,
  modelId: '',
  localModelPath: '',
  discoveredModels: [],
  lastDiscoveredAt: 0,
  ...overrides,
});

describe('restoreRedactedApiKeys', () => {
  it('remote hasApiKey=true + local 有非空 key → 恢复本地 key', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true })],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: 'sk-local-secret' })],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints[0].apiKey).toBe('sk-local-secret');
    expect(restored.endpoints[0].hasApiKey).toBe(true);
  });

  it('remote hasApiKey=false → 不恢复, apiKey 保持空 (用户主动清空信号)', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: false })],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: 'sk-old-key' })],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    // 用户在 UI 上清空 key 后存盘 → remote.hasApiKey=false → 哪怕 local
    // 缓存里有旧 key, 也绝不能用旧值覆盖回去 (会复活用户已经删除的凭据).
    expect(restored.endpoints[0].apiKey).toBe('');
    expect(restored.endpoints[0].hasApiKey).toBe(false);
  });

  it('remote 缺 hasApiKey 字段 → 视为 False, 不恢复 (legacy 兼容)', () => {
    // alpha.7 schema 没有 hasApiKey 字段; 用 unknown 双断言模拟老格式.
    // 直接传 AppSettings['endpoints'][number] 会被 TS 拒 (hasApiKey 是 optional).
    const legacyEndpoint = {
      id: 'e1',
      name: 'LM Studio',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKey: '',
      protocol: 'openai-compatible',
      modelId: '',
      localModelPath: '',
      discoveredModels: [],
      lastDiscoveredAt: 0,
    } as unknown as AppSettings['endpoints'][number];
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [legacyEndpoint],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: 'sk-legacy' })],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints[0].apiKey).toBe('');
  });

  it('local 为 null → 返回 remote 原样 (首次启动 / 缓存为空)', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true })],
    };
    const restored = restoreRedactedApiKeys(remote, null);
    expect(restored.endpoints[0].apiKey).toBe('');
    expect(restored.endpoints[0].hasApiKey).toBe(true);
  });

  it('local 有 endpoint, remote 没有 (用户删除端点) → remote 不变', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true })],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        fullEndpoint({ id: 'e1', apiKey: 'sk-1' }),
        fullEndpoint({ id: 'e2', apiKey: 'sk-2' }),
      ],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints).toHaveLength(1);
    expect(restored.endpoints[0].id).toBe('e1');
    expect(restored.endpoints[0].apiKey).toBe('sk-1');
  });

  it('remote 有 endpoint, local 没有 (新端点) → 不恢复, apiKey 保持空', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true }),
        fullEndpoint({ id: 'e2', apiKey: '', hasApiKey: true }),
      ],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: 'sk-1' })],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints).toHaveLength(2);
    expect(restored.endpoints[0].apiKey).toBe('sk-1');
    expect(restored.endpoints[1].apiKey).toBe('');
  });

  it('endpoint 顺序按 remote 排列, 与 local 不同也无影响', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true }),
        fullEndpoint({ id: 'e2', apiKey: '', hasApiKey: true }),
      ],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      // local 顺序相反
      endpoints: [
        fullEndpoint({ id: 'e2', apiKey: 'sk-2' }),
        fullEndpoint({ id: 'e1', apiKey: 'sk-1' }),
      ],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints[0].id).toBe('e1');
    expect(restored.endpoints[0].apiKey).toBe('sk-1');
    expect(restored.endpoints[1].id).toBe('e2');
    expect(restored.endpoints[1].apiKey).toBe('sk-2');
  });

  it('local endpoint apiKey 是空串 → 不恢复 (本地也没 key)', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true })],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [fullEndpoint({ id: 'e1', apiKey: '' })],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints[0].apiKey).toBe('');
  });

  it('不修改入参 remote / local 的 endpoints 数组与字段', () => {
    const remoteSnapshot = fullEndpoint({ id: 'e1', apiKey: '', hasApiKey: true });
    const localSnapshot = fullEndpoint({ id: 'e1', apiKey: 'sk-local' });
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [remoteSnapshot],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [localSnapshot],
    };

    restoreRedactedApiKeys(remote, local);

    // 入参未被 mutate
    expect(remote.endpoints[0].apiKey).toBe('');
    expect(remote.endpoints[0].hasApiKey).toBe(true);
    expect(local.endpoints[0].apiKey).toBe('sk-local');
  });

  it('endpoints 为空数组 → 直接返回 remote 原样', () => {
    const remote: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [],
    };
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [],
    };
    const restored = restoreRedactedApiKeys(remote, local);
    expect(restored.endpoints).toEqual([]);
  });
});
