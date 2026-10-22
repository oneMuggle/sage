import { describe, expect, it } from 'vitest';

import { auditSkillsApiGovernance } from '../skillsApi';

describe('skillsApi P146 governance audit', () => {
  it('returns healthy defaults for skillsApi governance', () => {
    const res = auditSkillsApiGovernance();
    expect(res.module).toBe('src/shared/api/skillsApi.ts');
    expect(res.phase).toBe('P146');
    expect(res.skillCount).toBe(0);
    expect(res.supportsConsolidation).toBe(true);
    expect(res.supportsRollback).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes skillCount and consolidation/rollback flags', () => {
    const res = auditSkillsApiGovernance({
      skillCount: 14.9,
      supportsConsolidation: true,
      supportsRollback: false,
    });
    expect(res.skillCount).toBe(14);
    expect(res.supportsRollback).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
