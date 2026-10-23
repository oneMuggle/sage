import { describe, expect, it } from 'vitest';

import { auditSkillLinkGovernance } from '../skillLink';

describe('auditSkillLinkGovernance (P167)', () => {
  it('returns compliant governance audit metadata for skillLink', () => {
    const report = auditSkillLinkGovernance();
    expect(report.module).toBe('src/features/scheduled/skillLink.ts');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('scheduled');
    expect(report.supportsSlashSkillExtraction).toBe(true);
    expect(report.supportsInvalidSkillDetection).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
