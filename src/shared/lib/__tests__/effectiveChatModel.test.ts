import { describe, expect, it } from 'vitest';

import type { EndpointConfig, ModelSelection } from '../../../entities/setting/types';
import { resolveEffectiveChatModel } from '../effectiveChatModel';

function endpoint(id: string, models: string[], apiKey = ''): EndpointConfig {
  return {
    id,
    name: id,
    baseUrl: `https://${id}.example/v1`,
    apiKey,
    discoveredModels: models.map((modelId) => ({
      id: modelId,
      capabilities: ['chat'],
      endpointId: id,
    })),
  } as unknown as EndpointConfig;
}

const globalSelection: ModelSelection = {
  endpointId: 'global-ep',
  modelId: 'text-model',
};

const endpoints: EndpointConfig[] = [
  endpoint('global-ep', ['text-model', 'same-ep-vision']),
  endpoint('vision-ep', ['vision-model'], 'sk-vision'),
];

describe('resolveEffectiveChatModel', () => {
  it('uses the global selection when there is no session override', () => {
    const result = resolveEffectiveChatModel(globalSelection, endpoints, null);

    expect(result.modelId).toBe('text-model');
    expect(result.endpoint?.id).toBe('global-ep');
  });

  it('uses the override model and its owning endpoint when they differ', () => {
    const result = resolveEffectiveChatModel(globalSelection, endpoints, 'vision-model');

    expect(result.modelId).toBe('vision-model');
    expect(result.endpoint?.id).toBe('vision-ep');
  });

  it('keeps the global endpoint when the override lives on the same endpoint', () => {
    // 回归：此前只在 endpoint 不同才应用覆盖，同端点覆盖被静默丢弃。
    const result = resolveEffectiveChatModel(globalSelection, endpoints, 'same-ep-vision');

    expect(result.modelId).toBe('same-ep-vision');
    expect(result.endpoint?.id).toBe('global-ep');
  });

  it('falls back to the global selection when the override is unknown', () => {
    const result = resolveEffectiveChatModel(globalSelection, endpoints, 'ghost-model');

    expect(result.modelId).toBe('text-model');
    expect(result.endpoint?.id).toBe('global-ep');
  });

  it('treats an override equal to the global model as the global selection', () => {
    const result = resolveEffectiveChatModel(globalSelection, endpoints, 'text-model');

    expect(result.modelId).toBe('text-model');
    expect(result.endpoint?.id).toBe('global-ep');
  });

  it('returns an empty model when nothing is selected', () => {
    const result = resolveEffectiveChatModel(
      { endpointId: null, modelId: null },
      endpoints,
      null,
    );

    expect(result.modelId).toBe('');
    expect(result.endpoint).toBeUndefined();
  });
});
