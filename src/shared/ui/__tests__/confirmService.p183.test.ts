import { describe, expect, it } from 'vitest';

import { auditConfirmServiceGovernance } from '../ConfirmDialog/confirmService';

describe('auditConfirmServiceGovernance (Phase P183)', () => {
  it('returns deterministic P183 governance audit payload', () => {
    const payload = JSON.parse(auditConfirmServiceGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('confirm-service');
    expect(payload.phase).toBe('P183');
    expect(payload.audited).toBe(true);
  });
});
