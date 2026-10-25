import { describe, expect, it } from 'vitest';

import { auditSessionIdBadgeGovernance } from '../SessionIdBadge';

describe('auditSessionIdBadgeGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditSessionIdBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('session-id-badge');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
