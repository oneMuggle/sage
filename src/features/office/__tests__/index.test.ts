import { describe, expect, it } from 'vitest';

import { auditOfficeFeatureBarrel, exportOfficeFeatureBarrelAuditJson } from '../index';

describe('office feature barrel audit diagnostics', () => {
  it('audits exported symbols of src/features/office/index.ts', () => {
    const report = auditOfficeFeatureBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/features/office/index.ts');
    expect(report.symbolCount).toBe(19);
    expect(report.exportedSymbols).toContain('OfficeCapabilityBar');
    expect(report.exportedSymbols).toContain('OfficeDuplicateDialog');
    expect(report.exportedSymbols).toContain('OfficeCompareDialog');
    expect(report.exportedSymbols).toContain('WordTemplateFillDialog');
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportOfficeFeatureBarrelAuditJson());
    expect(parsed.symbolCount).toBe(19);
    expect(parsed.exportedAt).toBe('2026-11-24');
  });
});
