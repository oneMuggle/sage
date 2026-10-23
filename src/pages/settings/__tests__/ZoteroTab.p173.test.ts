import { describe, expect, it } from 'vitest';

import { auditZoteroTabGovernance } from '../ZoteroTab';

describe('auditZoteroTabGovernance (P173)', () => {
  it('returns compliant governance audit metadata for ZoteroTab', () => {
    const report = auditZoteroTabGovernance();
    expect(report.module).toBe('src/pages/settings/ZoteroTab.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsItemSearchAndAnnotationsPreview).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
