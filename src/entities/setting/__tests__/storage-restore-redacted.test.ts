/**
 * 2026-08-26 (OWASP A02:2021): 单测 restoreRedactedApiKeys 纯函数.
 *
 * 这是 storage.loadSettings 里 "脱敏 GET 不能覆盖本地 key" 的核心防护.
 * 验证以下契约:
 *   - 远程 {apiKey:'', hasApiKey:true} + 本地有非空 key → 按 id 匹配恢复本地值
 *   - 远程 {apiKey:'', hasApiKey:false} → 不还原 (用户从未设置)
 *   - 远程 {apiKey:''} (无 hasApiKey 字段, 历史响应) → 不还原 (避免覆盖)
 *   - 远程 apiKey 非空 (后端未脱敏) → 原样返回
 *   - id 不匹配 → 不还原
 *   - local 没有该 endpoint → 不凭空捏造
 *   - 顺序错位 (local 与 remote endpoint 数组顺序不同) → 按 id 匹配而非按 index
 *   - 入参非对象 → 原样返回 (防御性)
 */
import { describe, expect, it } from 'vitest';

import { restoreRedactedApiKeys } from '../storage';
import { DEFAULT_SETTINGS, type AppSettings } from '../types';

function ep(id: string, apiKey: string, extra: Partial<AppSettings['endpoints'][number]> = {}) {
  return {
    id,
    name: id,
    baseUrl: 'http://localhost',
    apiKey,
    protocol: 'openai-compatible' as const,
    modelId: '',
    localModelPath: '',
    discoveredModels: [],
    lastDiscoveredAt: null,
    ...extra,
  };
}

describe('restoreRedactedApiKeys (2026-08-26)', () => {
  it('local 有真实 key + remote 脱敏 (hasApiKey=true) → 按 id 恢复本地值', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-REAL')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', ''), hasApiKey: true }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('sk-LOCAL-REAL');
    // hasApiKey 保留 — 让下游 deepMerge 不再覆盖这个 endpoint 的其它字段
    expect(result.endpoints?.[0].hasApiKey).toBe(true);
  });

  it('remote hasApiKey=false → 用户从未设置 key, 不还原', () => {
    // 防止从 local 兜底凭空捏造 key: local 有真实 key, 但 remote 显式说
    // hasApiKey=false, 说明用户主动清空. 我们尊重 remote 的真相.
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-REAL')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', ''), hasApiKey: false }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('');
    expect(result.endpoints?.[0].hasApiKey).toBe(false);
  });

  it('remote 没 hasApiKey 字段 (历史响应) → 不动 apiKey, 避免覆盖真实值', () => {
    // 旧后端没有 redact_secrets, apiKey 是真实值或空. 这里 apiKey='' 可能是
    // 真实空, 也可能是历史污染. 我们无法区分, 选择不动.
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-REAL')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', '')], // no hasApiKey
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('');
  });

  it('remote apiKey 非空 (后端未脱敏) → 原样保留, 不覆盖', () => {
    // 后端万一没脱敏 (e.g. 调试场景) → apiKey 是真值, 不该被 local 覆盖.
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-OLD')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', 'sk-REMOTE-NEW'), hasApiKey: true }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('sk-REMOTE-NEW');
  });

  it('id 不匹配 → 不还原, 走 deepMerge 字段比较 (remote-wins → 空)', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('local-only', 'sk-LOCAL-REAL')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('remote-only', ''), hasApiKey: true }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('');
    expect(result.endpoints?.[0].id).toBe('remote-only');
  });

  it('local 无对应 id → 不凭空捏造 key', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', ''), hasApiKey: true }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('');
  });

  it('顺序错位 → 按 id 而非 index 匹配', () => {
    // local: [e1, e2]  remote: [e2, e1]  — 还原必须按 id, 不是按数组 index.
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-1'), ep('e2', 'sk-LOCAL-2')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        { ...ep('e2', ''), hasApiKey: true },
        { ...ep('e1', ''), hasApiKey: true },
      ],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('sk-LOCAL-2');
    expect(result.endpoints?.[1].apiKey).toBe('sk-LOCAL-1');
  });

  it('local.apiKey 为空 + remote 脱敏 → 保持空 (用户清空过, 不能从无到有)', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', '')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', ''), hasApiKey: true }],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('');
  });

  it('remote 非对象 → 原样返回 (防御性)', () => {
    expect(restoreRedactedApiKeys(null as unknown as AppSettings, {})).toBeNull();
    const empty = {} as AppSettings;
    expect(restoreRedactedApiKeys(empty, {})).toBe(empty);
  });

  it('remote.endpoints 不是数组 → 原样返回', () => {
    const remote = {
      ...DEFAULT_SETTINGS,
      endpoints: 'oops' as unknown as AppSettings['endpoints'],
    };
    expect(restoreRedactedApiKeys(remote, {})).toBe(remote);
  });

  it('混合: 多 endpoint 列表, 部分脱敏部分未脱敏', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-1'), ep('e2', 'sk-LOCAL-2'), ep('e3', '')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        { ...ep('e1', ''), hasApiKey: true }, // 脱敏
        { ...ep('e2', 'sk-REMOTE-2'), hasApiKey: true }, // 未脱敏 (unusual)
        { ...ep('e3', ''), hasApiKey: false }, // 用户清空
      ],
    };
    const result = restoreRedactedApiKeys(remote, local);
    expect(result.endpoints?.[0].apiKey).toBe('sk-LOCAL-1');
    expect(result.endpoints?.[1].apiKey).toBe('sk-REMOTE-2');
    expect(result.endpoints?.[2].apiKey).toBe('');
  });

  it('不修改入参 — 纯函数契约', () => {
    const local: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [ep('e1', 'sk-LOCAL-REAL')],
    };
    const remote: Partial<AppSettings> = {
      ...DEFAULT_SETTINGS,
      endpoints: [{ ...ep('e1', ''), hasApiKey: true }],
    };
    const beforeRemote = JSON.parse(JSON.stringify(remote));
    const beforeLocal = JSON.parse(JSON.stringify(local));
    restoreRedactedApiKeys(remote, local);
    expect(remote).toEqual(beforeRemote);
    expect(local).toEqual(beforeLocal);
  });
});
