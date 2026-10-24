import { describe, expect, it } from 'vitest';

import { auditConstraintManagerGovernance } from '../ConstraintManager';

describe('auditConstraintManagerGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditConstraintManagerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('constraint-manager');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
