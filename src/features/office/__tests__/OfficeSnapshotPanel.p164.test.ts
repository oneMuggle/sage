import { describe, expect, it } from 'vitest';

import {
  auditOfficeSnapshotPanel,
  auditOfficeSnapshotPanelGovernance,
  exportOfficeSnapshotPanelAuditJson,
} from '../OfficeSnapshotPanel';

describe('OfficeSnapshotPanel governance audit (P164)', () => {
  it('returns ready governance status for OfficeSnapshotPanel', () => {
    const snap = auditOfficeSnapshotPanelGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeSnapshotPanel.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('audits office snapshot panel report and json', () => {
    expect(auditOfficeSnapshotPanel(5).snapshotCount).toBe(5);
    expect(JSON.parse(exportOfficeSnapshotPanelAuditJson(3)).snapshotCount).toBe(3);
  });
});
