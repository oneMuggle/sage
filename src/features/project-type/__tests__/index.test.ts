import { describe, expect, it } from 'vitest';

import { auditProjectTypeFeatureBarrel, exportProjectTypeFeatureBarrelAuditJson } from '../index';

describe('project-type feature barrel audit diagnostics', () => {
  it('audits exported symbols of src/features/project-type/index.ts', () => {
    const report = auditProjectTypeFeatureBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/features/project-type/index.ts');
    expect(report.symbolCount).toBe(16);
    expect(report.exportedSymbols).toContain('ProjectArchetypeStudio');
    expect(report.exportedSymbols).toContain('ProjectAnalysisWizard');
    expect(report.exportedSymbols).toContain('ProjectAnalysisReport');
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportProjectTypeFeatureBarrelAuditJson());
    expect(parsed.symbolCount).toBe(16);
    expect(parsed.exportedAt).toBe('2026-10-27');
  });
});
