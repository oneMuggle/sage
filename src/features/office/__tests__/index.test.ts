import { describe, expect, it } from 'vitest';

import {
  auditOfficeFeatureBarrel,
  exportOfficeFeatureBarrelAuditJson,
} from '../index';

describe('office feature barrel audit diagnostics', () => {
  it('audits exported symbols of src/features/office/index.ts', () => {
    const report = auditOfficeFeatureBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/features/office/index.ts');
<<<<<<< HEAD
    expect(report.symbolCount).toBe(12);
=======
    expect(report.symbolCount).toBe(13);
>>>>>>> origin/main
    expect(report.exportedSymbols).toContain('OfficeCapabilityBar');
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportOfficeFeatureBarrelAuditJson());
<<<<<<< HEAD
    expect(parsed.symbolCount).toBe(12);
=======
    expect(parsed.symbolCount).toBe(13);
>>>>>>> origin/main
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
