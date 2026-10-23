import { describe, expect, it } from 'vitest';

import { evaluateSkillsBarrelGovernanceAudit } from '../index';

describe('evaluateSkillsBarrelGovernanceAudit (Phase P139)', () => {
  it('returns healthy report when all skill widget barrel exports are present', () => {
    const report = evaluateSkillsBarrelGovernanceAudit({
      exportedComponentNames: ['SkillList', 'SkillCard', 'SkillDraftList', 'SkillAuditDrawer'],
      hasSkillListExport: true,
      hasSkillCardExport: true,
      hasSkillAuditDrawerExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(4);
    expect(report.completeSkillExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags incomplete skill widget barrel exports', () => {
    const report = evaluateSkillsBarrelGovernanceAudit({
      exportedComponentNames: ['SkillList'],
      hasSkillListExport: true,
      hasSkillCardExport: false,
      hasSkillAuditDrawerExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SKILLS_BARREL_EXPORTS_LOW',
      'SKILLS_CORE_EXPORT_MISSING',
    ]);
  });
});
