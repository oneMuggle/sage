import { describe, expect, it } from 'vitest';

import { auditMemoryTabGovernance } from '../MemoryTab';

describe('auditMemoryTabGovernance (P172)', () => {
  it('returns compliant governance audit metadata for MemoryTab', () => {
    const report = auditMemoryTabGovernance();
    expect(report.module).toBe('src/pages/settings/MemoryTab.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.embedderModes).toEqual(['onnx', 'hash']);
    expect(report.supportsBackupsAndExport).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
