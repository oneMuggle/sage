import { describe, expect, it } from 'vitest';

import {
  formatOrchSubscriptionJson,
  formatOrchSubscriptionSummary,
} from '../useOrchEventSubscription';

describe('useOrchEventSubscription audit helpers', () => {
  it('formats orchestration event subscription summary', () => {
    expect(formatOrchSubscriptionSummary('run-42', true, 12)).toBe(
      'run=run-42 · enabled=true · lastSeq=12',
    );
    expect(formatOrchSubscriptionSummary(null, false, 0)).toBe(
      'run=none · enabled=false · lastSeq=0',
    );
  });

  it('serializes orchestration event subscription audit JSON', () => {
    expect(JSON.parse(formatOrchSubscriptionJson('run-99', true, 7))).toEqual({
      runId: 'run-99',
      enabled: true,
      lastSeq: 7,
    });
  });
});
