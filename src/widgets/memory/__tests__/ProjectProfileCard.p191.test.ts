import { describe, expect, it } from 'vitest';

import { auditProjectProfileCardGovernance } from '../ProjectProfileCard';

describe('auditProjectProfileCardGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditProjectProfileCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-profile-card');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
