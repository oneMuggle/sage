import { describe, expect, it } from 'vitest';

import { auditUpdatesTabGovernance } from '../UpdatesTab';

describe('auditUpdatesTabGovernance (P173)', () => {
  it('returns compliant governance audit metadata for UpdatesTab', () => {
    const report = auditUpdatesTabGovernance();
    expect(report.module).toBe('src/pages/settings/UpdatesTab.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsManualCheckAndCacheRetention).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
