import { describe, expect, it } from 'vitest';

import type { CandidateModel } from '../../../entities/model-catalog/types';
import { modelTaskFit } from '../modelTaskFit';
const model: CandidateModel = {
  model_key: { provider: 'test', model_id: 'test-model' },
  native: null,
  price: { input_per_million: null, output_per_million: null, currency: 'USD' },
  source: 'unknown',
  pricing_scope: 'unknown',
};
describe('capability metadata, not name heuristics', () => {
  it('does not recommend unknown tool capability for a document task', () => {
    expect(modelTaskFit(model, true)).toEqual({
      eligible: false,
      tools: 'unknown',
      knownPrice: false,
    });
  });
  it('preserves false and conflicting metadata instead of guessing', () => {
    expect(modelTaskFit({ ...model, capabilities: { tools: false } }, true).eligible).toBe(false);
    expect(
      modelTaskFit({ ...model, capabilities: { tools: true, tool_calling: false } }, true).tools,
    ).toBe('unknown');
    expect(modelTaskFit({ ...model, capabilities: { tools: true } }, true).eligible).toBe(true);
  });
  it('distinguishes known zero prices from unknown prices without estimating in the browser', () => {
    expect(
      modelTaskFit(
        { ...model, price: { input_per_million: '0', output_per_million: '0', currency: 'USD' } },
        false,
      ).knownPrice,
    ).toBe(true);
  });
});
