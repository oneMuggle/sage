import { describe, expect, it } from 'vitest';

import { auditAccountTableGovernance } from '../AccountTable';

describe('auditAccountTableGovernance (Phase P185)', () => {
  it('returns deterministic P185 governance audit payload', () => {
    const payload = JSON.parse(auditAccountTableGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('account-table');
    expect(payload.phase).toBe('P185');
    expect(payload.audited).toBe(true);
  });
});
