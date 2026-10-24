import { describe, expect, it } from 'vitest';

import { auditProjectApiGovernance } from '../projectApi';

describe('auditProjectApiGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditProjectApiGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-api');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
