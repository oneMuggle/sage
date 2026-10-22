import { describe, expect, it } from 'vitest';

import { auditSkillDraftsApiGovernance } from '../skillDraftsApi';

describe('skillDraftsApi P145 governance audit', () => {
  it('returns healthy defaults for skillDraftsApi governance', () => {
    const res = auditSkillDraftsApiGovernance();
    expect(res.module).toBe('src/shared/api/skillDraftsApi.ts');
    expect(res.phase).toBe('P145');
    expect(res.draftCount).toBe(0);
    expect(res.supportsAcceptReject).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes draftCount and supportsAcceptReject', () => {
    const res = auditSkillDraftsApiGovernance({
      draftCount: 5.5,
      supportsAcceptReject: false,
    });
    expect(res.draftCount).toBe(5);
    expect(res.supportsAcceptReject).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
