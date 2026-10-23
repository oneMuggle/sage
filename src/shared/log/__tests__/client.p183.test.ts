import { describe, expect, it } from 'vitest';

import { auditLogClientGovernance } from '../client';

describe('auditLogClientGovernance (Phase P183)', () => {
  it('returns deterministic P183 governance audit payload', () => {
    const payload = JSON.parse(auditLogClientGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('log-client');
    expect(payload.phase).toBe('P183');
    expect(payload.audited).toBe(true);
  });
});
