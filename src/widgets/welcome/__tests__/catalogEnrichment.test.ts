import { describe, expect, it } from 'vitest';

import type { CandidateModel } from '../../../entities/model-catalog/types';
import { buildCatalogEnricher } from '../catalogEnrichment';

function item(provider: string, modelId: string, scope: string, native = 8000): CandidateModel {
  return {
    model_key: { provider, model_id: modelId },
    tier: 'balanced',
    native,
    price: { input_per_million: '1.00', output_per_million: '2.00', currency: 'USD' },
    source: 'builtin',
    pricing_scope: scope,
  };
}

describe('buildCatalogEnricher', () => {
  it('精确唯一命中时返回该条', () => {
    const enrich = buildCatalogEnricher([item('openai', 'gpt-4o', 'openai', 128000)]);
    expect(enrich('gpt-4o')?.native).toBe(128000);
  });

  it('未命中返回 null', () => {
    const enrich = buildCatalogEnricher([item('openai', 'gpt-4o', 'openai')]);
    expect(enrich('claude-3')).toBeNull();
  });

  it('同一裸 id 出现在两个 provider 下视为歧义, 不回退到后缀匹配', () => {
    const enrich = buildCatalogEnricher([
      item('openai', 'gpt-4o', 'openai', 128000),
      item('azure', 'gpt-4o', 'azure', 32000),
      item('openrouter', 'openrouter/gpt-4o', 'openrouter', 64000),
    ]);
    expect(enrich('gpt-4o')).toBeNull();
  });

  it('裸 id 唯一命中带前缀的 catalog 条目', () => {
    const enrich = buildCatalogEnricher([
      item('meta-llama', 'meta-llama/llama-3.1-70b', 'meta-llama', 131072),
    ]);
    expect(enrich('llama-3.1-70b')?.native).toBe(131072);
  });

  it('后缀匹配出现多条时视为歧义', () => {
    const enrich = buildCatalogEnricher([
      item('meta-llama', 'meta-llama/llama-x', 'a'),
      item('together', 'together/llama-x', 'b'),
    ]);
    expect(enrich('llama-x')).toBeNull();
  });

  it('同一条目重复出现不算歧义', () => {
    const enrich = buildCatalogEnricher([
      item('openai', 'gpt-4o', 'openai', 128000),
      item('openai', 'gpt-4o', 'openai', 128000),
    ]);
    expect(enrich('gpt-4o')?.native).toBe(128000);
  });
});
