import { describe, expect, it } from 'vitest';

import { auditOfficeApiGovernance } from '../officeApi';

describe('auditOfficeApiGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditOfficeApiGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('office-api');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
