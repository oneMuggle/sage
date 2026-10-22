import { describe, expect, it } from 'vitest';

import {
  auditTransparencyPayload,
  exportTransparencyPayloadAuditJson,
} from '../transparencyPayload';

describe('transparencyPayload audit diagnostics', () => {
  it('audits valid and invalid compact payloads', () => {
    const valid = auditTransparencyPayload();
    expect(valid.schemaVersion).toBe('1.0');
    expect(valid.module).toBe('src/features/send-message/transparencyPayload.ts');
    expect(valid.validatorCount).toBe(5);
    expect(valid.sampleCompactValid).toBe(true);

    const invalid = auditTransparencyPayload(null);
    expect(invalid.sampleCompactValid).toBe(false);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportTransparencyPayloadAuditJson());
    expect(parsed.sampleCompactValid).toBe(true);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
