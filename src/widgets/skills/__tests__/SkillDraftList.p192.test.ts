import { describe, expect, it } from 'vitest';

import { auditSkillDraftListGovernance } from '../SkillDraftList';

describe('auditSkillDraftListGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditSkillDraftListGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('skill-draft-list');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
