import { describe, expect, it } from 'vitest';

import { auditButtonGovernance } from '../Button';

describe('auditButtonGovernance (Phase P184)', () => {
  it('returns deterministic P184 governance audit payload', () => {
    const payload = JSON.parse(auditButtonGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('ui-button');
    expect(payload.phase).toBe('P184');
    expect(payload.audited).toBe(true);
  });
});
