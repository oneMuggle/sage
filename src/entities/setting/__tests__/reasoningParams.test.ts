/**
 * 思考过程参数 (reasoningEffort / thinkingBudget) 存储层测试。
 *
 * 2026-11-03: per-endpoint 思考过程参数落地。
 *
 * 覆盖：
 * - DEFAULT_ENDPOINT 两字段默认 null（= 不发送该键，上游不进入思考模式）
 * - sanitizeForBackend 放行两字段（漏加白名单 → 配置静默丢弃 → 思考过程永远不出现）
 */
import { describe, expect, it } from 'vitest';

import { __test__sanitizeForBackend } from '../storage';
import { DEFAULT_ENDPOINT, type EndpointConfig } from '../types';

type LooseEndpoint = Partial<EndpointConfig> & Record<string, unknown>;
type LooseSettings = Record<string, unknown>;

describe('思考过程参数 (reasoningEffort / thinkingBudget)', () => {
  it('DEFAULT_ENDPOINT 两字段默认为 null', () => {
    expect(DEFAULT_ENDPOINT.reasoningEffort).toBeNull();
    expect(DEFAULT_ENDPOINT.thinkingBudget).toBeNull();
  });

  it('sanitizeForBackend 保留 endpoints[*] 内的 reasoningEffort / thinkingBudget', () => {
    const out = __test__sanitizeForBackend({
      endpoints: [
        {
          id: 'ep1',
          name: 'Test',
          baseUrl: 'https://api.example.test/v1',
          reasoningEffort: 'high',
          thinkingBudget: 4096,
        },
      ],
    } as unknown as LooseSettings) as unknown as { endpoints: LooseEndpoint[] };

    const ep = out.endpoints[0];
    expect(ep.reasoningEffort).toBe('high');
    expect(ep.thinkingBudget).toBe(4096);
  });

  it('sanitizeForBackend 保留 null 值（未设置也要原样回传）', () => {
    const out = __test__sanitizeForBackend({
      endpoints: [
        {
          id: 'ep1',
          reasoningEffort: null,
          thinkingBudget: null,
        },
      ],
    } as unknown as LooseSettings) as unknown as { endpoints: LooseEndpoint[] };

    const ep = out.endpoints[0];
    expect(ep.reasoningEffort).toBeNull();
    expect(ep.thinkingBudget).toBeNull();
  });

  it('sanitizeForBackend 仍然剥离端点内的未知字段', () => {
    const out = __test__sanitizeForBackend({
      endpoints: [
        {
          id: 'ep1',
          reasoningEffort: 'low',
          totallyUnknownField: 'x',
        },
      ],
    } as unknown as LooseSettings) as unknown as { endpoints: LooseEndpoint[] };

    expect(out.endpoints[0].totallyUnknownField).toBeUndefined();
    expect(out.endpoints[0].reasoningEffort).toBe('low');
  });
});
