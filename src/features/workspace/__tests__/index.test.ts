import { describe, expect, it } from 'vitest';

import {
  auditWorkspaceFeatureBarrel,
  exportWorkspaceFeatureBarrelAuditJson,
} from '../index';

describe('workspace feature barrel audit diagnostics', () => {
  it('audits exported symbols of src/features/workspace/index.ts', () => {
    const report = auditWorkspaceFeatureBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/features/workspace/index.ts');
    expect(report.symbolCount).toBe(2);
    expect(report.exportedSymbols).toEqual(['WorkspaceBindModal', 'WorkspaceEmptyGuard']);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportWorkspaceFeatureBarrelAuditJson());
    expect(parsed.symbolCount).toBe(2);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
