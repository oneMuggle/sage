import { describe, expect, it } from 'vitest';

import {
  FIELD_LABELS,
  formatCandidateModelJson,
  formatCandidateModelSummary,
  REVIEWABLE_FIELDS,
  SOURCE_LABELS,
} from '../types';

describe('model-catalog types', () => {
  it('exports reviewable fields and labels', () => {
    expect(REVIEWABLE_FIELDS).toHaveLength(5);
    expect(FIELD_LABELS.native).toBe('上下文窗口');
    expect(SOURCE_LABELS.builtin).toBe('内置默认值');
  });

  it('formats candidate model summary and JSON (Phase P120)', () => {
    const model = {
      model_key: { provider: 'openai', model_id: 'gpt-4o' },
      native: 128000,
      service: 128000,
      price: { input_per_million: '2.50', output_per_million: '10.00', currency: 'USD' as const },
      source: 'builtin',
      pricing_scope: 'public',
    };
    expect(formatCandidateModelSummary(model)).toBe(
      'openai/gpt-4o · ctx=128000 · source=builtin',
    );
    expect(JSON.parse(formatCandidateModelJson(model))).toEqual({
      provider: 'openai',
      modelId: 'gpt-4o',
      nativeContext: 128000,
      serviceContext: 128000,
      source: 'builtin',
      pricingScope: 'public',
    });
  });
});
