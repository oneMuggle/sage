import { describe, expect, it } from 'vitest';

import { auditSkillListGovernance } from '../SkillList';

describe('auditSkillListGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditSkillListGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('skill-list');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
