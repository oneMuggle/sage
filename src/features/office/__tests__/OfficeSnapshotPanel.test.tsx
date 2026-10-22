import { describe, expect, it } from 'vitest';

import {
  auditOfficeSnapshotPanel,
  exportOfficeSnapshotPanelAuditJson,
} from '../OfficeSnapshotPanel';

describe('OfficeSnapshotPanel audit diagnostics', () => {
  it('audits snapshot count and capabilities', () => {
    const def = auditOfficeSnapshotPanel();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/features/office/OfficeSnapshotPanel.tsx');
    expect(def.snapshotCount).toBe(0);
    expect(def.supportsRestore).toBe(true);
    expect(def.supportsDiffPreview).toBe(true);

    expect(auditOfficeSnapshotPanel(-5).snapshotCount).toBe(0);
    expect(auditOfficeSnapshotPanel(7).snapshotCount).toBe(7);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportOfficeSnapshotPanelAuditJson(5));
    expect(parsed.componentName).toBe('OfficeSnapshotPanel');
    expect(parsed.snapshotCount).toBe(5);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
