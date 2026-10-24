import { describe, expect, it } from 'vitest';

import { auditTurnGroupingGovernance } from '../turnGrouping';

describe('auditTurnGroupingGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditTurnGroupingGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('turn-grouping');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
