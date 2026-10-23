import { describe, expect, it } from 'vitest';

import {
  auditAccountTable,
  exportAccountTableAuditJson,
} from '../AccountTable';

describe('AccountTable audit diagnostics', () => {
  it('audits account counts and clamps bounds', () => {
    const def = auditAccountTable();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/widgets/arena/AccountTable.tsx');
    expect(def.accountCount).toBe(0);
    expect(def.activeCount).toBe(0);

    const clamped = auditAccountTable(5, 9);
    expect(clamped.accountCount).toBe(5);
    expect(clamped.activeCount).toBe(5);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportAccountTableAuditJson(8, 6));
    expect(parsed.componentName).toBe('AccountTable');
    expect(parsed.accountCount).toBe(8);
    expect(parsed.activeCount).toBe(6);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
