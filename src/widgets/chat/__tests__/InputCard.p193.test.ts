import { describe, expect, it } from 'vitest';

import { auditInputCardGovernance } from '../InputCard';

describe('auditInputCardGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditInputCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('input-card');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
