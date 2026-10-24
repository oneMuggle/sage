import { describe, expect, it } from 'vitest';

import { auditUserProfileCardGovernance } from '../UserProfileCard';

describe('auditUserProfileCardGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditUserProfileCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('user-profile-card');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
