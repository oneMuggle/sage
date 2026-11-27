import { describe, expect, it } from 'vitest';

import type { EndpointConfig } from '../../../entities/setting/types';
import { moveEndpoint } from '../endpointPriority';

const ep = (id: string): EndpointConfig => ({
  id,
  name: id,
  baseUrl: '',
  apiKey: '',
  protocol: 'openai-compatible',
  modelId: '',
  localModelPath: '',
  discoveredModels: [],
  lastDiscoveredAt: null,
  reasoningEffort: null,
  thinkingBudget: null,
});

describe('moveEndpoint', () => {
  it('swaps neighbors and renumbers priorities', () => {
    const moved = moveEndpoint([ep('a'), ep('b'), ep('c')], 1, -1);
    expect(moved.map((e) => e.id)).toEqual(['b', 'a', 'c']);
    expect(moved.map((e) => e.priority)).toEqual([1, 2, 3]);
    expect(moved).toHaveLength(3);
  });

  it('is a no-op at boundaries but still normalizes priorities', () => {
    const input = [ep('a'), ep('b')];
    const up = moveEndpoint(input, 0, -1);
    expect(up.map((e) => e.id)).toEqual(['a', 'b']);
    expect(up.map((e) => e.priority)).toEqual([1, 2]);
    const down = moveEndpoint(input, 1, 1);
    expect(down.map((e) => e.id)).toEqual(['a', 'b']);
  });

  it('does not mutate the input array', () => {
    const input = [ep('a'), ep('b')];
    moveEndpoint(input, 0, 1);
    expect(input.map((e) => e.id)).toEqual(['a', 'b']);
  });
});
