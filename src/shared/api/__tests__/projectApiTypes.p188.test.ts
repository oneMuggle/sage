import { describe, expect, it } from 'vitest';

import { auditProjectApiTypesGovernance } from '../projectApiTypes';

describe('auditProjectApiTypesGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditProjectApiTypesGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-api-types');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
