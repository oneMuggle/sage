import { describe, expect, it } from 'vitest';

import { auditSkillDraftDetailGovernance } from '../SkillDraftDetail';

describe('auditSkillDraftDetailGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditSkillDraftDetailGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('skill-draft-detail');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
