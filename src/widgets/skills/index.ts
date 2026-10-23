/**
 * Skills Widgets - Skill list & card UI components
 */
export { default as SkillList } from './SkillList';
export { default as SkillCard } from './SkillCard';
export { default as SkillDraftList } from './SkillDraftList';
export { default as SkillAuditDrawer } from './SkillAuditDrawer';

export interface SkillsBarrelAuditInput {
  exportedComponentNames: string[];
  hasSkillListExport: boolean;
  hasSkillCardExport: boolean;
  hasSkillAuditDrawerExport: boolean;
}

export interface SkillsBarrelAuditReport {
  uniqueExportCount: number;
  completeSkillExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateSkillsBarrelGovernanceAudit(
  input: SkillsBarrelAuditInput,
): SkillsBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponentNames
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 4) {
    issueCodes.push('SKILLS_BARREL_EXPORTS_LOW');
  }
  const completeSkillExports =
    input.hasSkillListExport && input.hasSkillCardExport && input.hasSkillAuditDrawerExport;
  if (!completeSkillExports) {
    issueCodes.push('SKILLS_CORE_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    completeSkillExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
