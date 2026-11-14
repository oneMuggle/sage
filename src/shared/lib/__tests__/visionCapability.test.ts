import { describe, expect, it } from 'vitest';

import type { EffectiveModel } from '../../../entities/model-catalog/types';
import type { EndpointConfig } from '../../../entities/setting/types';
import { resolveVisionSupport, toRequestCapabilities } from '../visionCapability';

function makeEndpoint(
  models: { id: string; capabilities: ('chat' | 'vision' | 'embedding')[] }[],
): EndpointConfig {
  return { discoveredModels: models } as unknown as EndpointConfig;
}

function makeCatalog(vision: boolean | null | undefined): EffectiveModel {
  return {
    model_key: { provider: 'custom', model_id: 'm1' },
    tier: 'balanced',
    capabilities: vision === null || vision === undefined ? null : { vision },
    limits: { native: null, service: null },
    price: { input_per_million: null, output_per_million: null, currency: 'USD' },
    provenance: {},
    revision: 1,
  };
}

describe('resolveVisionSupport', () => {
  it('returns unknown when endpoint or model id is missing', () => {
    expect(resolveVisionSupport(undefined, 'gpt-4o')).toBe('unknown');
    expect(resolveVisionSupport(makeEndpoint([]), null)).toBe('unknown');
    expect(resolveVisionSupport(makeEndpoint([]), '')).toBe('unknown');
  });

  it('trusts catalog capabilities.vision = true over discovered heuristics', () => {
    const endpoint = makeEndpoint([{ id: 'm1', capabilities: ['chat'] }]);
    expect(resolveVisionSupport(endpoint, 'm1', makeCatalog(true))).toBe('supported');
  });

  it('trusts catalog capabilities.vision = false over discovered heuristics', () => {
    const endpoint = makeEndpoint([{ id: 'm1', capabilities: ['chat', 'vision'] }]);
    expect(resolveVisionSupport(endpoint, 'm1', makeCatalog(false))).toBe('unsupported');
  });

  it('falls back to discoveredModels when catalog capabilities are null', () => {
    const supported = makeEndpoint([{ id: 'm1', capabilities: ['chat', 'vision'] }]);
    const unsupported = makeEndpoint([{ id: 'm1', capabilities: ['chat'] }]);
    expect(resolveVisionSupport(supported, 'm1', makeCatalog(null))).toBe('supported');
    expect(resolveVisionSupport(unsupported, 'm1', makeCatalog(null))).toBe('unsupported');
  });

  it('falls back to discoveredModels when catalog is unavailable', () => {
    const endpoint = makeEndpoint([{ id: 'm1', capabilities: ['chat', 'vision'] }]);
    expect(resolveVisionSupport(endpoint, 'm1', null)).toBe('supported');
  });

  it('returns unknown when the model is absent from discoveredModels', () => {
    const endpoint = makeEndpoint([{ id: 'other', capabilities: ['chat'] }]);
    expect(resolveVisionSupport(endpoint, 'm1')).toBe('unknown');
  });
});

describe('toRequestCapabilities', () => {
  it('only strips vision for explicit unsupported', () => {
    expect(toRequestCapabilities('unsupported')).toEqual(['chat']);
    expect(toRequestCapabilities('supported')).toEqual(['chat', 'vision']);
    expect(toRequestCapabilities('unknown')).toEqual(['chat', 'vision']);
  });
});
