import { describe, expect, it } from 'vitest';

import {
  auditOfficeCapabilityBar,
  exportOfficeCapabilityBarAuditJson,
} from '../OfficeCapabilityBar';

describe('OfficeCapabilityBar audit diagnostics', () => {
  it('audits default and probing states', () => {
    const def = auditOfficeCapabilityBar();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/features/office/OfficeCapabilityBar.tsx');
    expect(def.capabilityCount).toBe(3);
    expect(def.isProbing).toBe(false);
    expect(def.hasRefreshAction).toBe(true);

    const probing = auditOfficeCapabilityBar(-2, true);
    expect(probing.capabilityCount).toBe(0);
    expect(probing.isProbing).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportOfficeCapabilityBarAuditJson(4, true));
    expect(parsed.componentName).toBe('OfficeCapabilityBar');
    expect(parsed.capabilityCount).toBe(4);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
