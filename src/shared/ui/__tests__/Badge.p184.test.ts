import { describe, expect, it } from 'vitest';

import { auditBadgeGovernance } from '../Badge';

describe('auditBadgeGovernance (Phase P184)', () => {
  it('returns deterministic P184 governance audit payload', () => {
    const payload = JSON.parse(auditBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('ui-badge');
    expect(payload.phase).toBe('P184');
    expect(payload.audited).toBe(true);
  });
});
