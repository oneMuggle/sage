import { describe, expect, it } from 'vitest';

import {
  auditArenaWidgetBarrel,
  exportArenaWidgetBarrelAuditJson,
} from '../index';

describe('arena widget barrel audit diagnostics', () => {
  it('audits exported symbols of src/widgets/arena/index.ts', () => {
    const report = auditArenaWidgetBarrel();
    expect(report.schemaVersion).toBe('1.0');
    expect(report.module).toBe('src/widgets/arena/index.ts');
    expect(report.symbolCount).toBe(7);
    expect(report.exportedSymbols).toContain('TokenWindowCard');
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportArenaWidgetBarrelAuditJson());
    expect(parsed.symbolCount).toBe(7);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
