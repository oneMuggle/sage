import { describe, expect, it } from 'vitest';

import { auditUpdateDialogGovernance } from '../UpdateDialog';

describe('UpdateDialog P152 governance audit', () => {
  it('returns healthy defaults for UpdateDialog governance', () => {
    const res = auditUpdateDialogGovernance();
    expect(res.module).toBe('src/components/UpdateDialog.tsx');
    expect(res.phase).toBe('P152');
    expect(res.progressPercent).toBe(0);
    expect(res.hasValidVersion).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('clamps progressPercent and flags unhealthy when hasValidVersion is false', () => {
    const res = auditUpdateDialogGovernance({
      progressPercent: 130,
      hasValidVersion: false,
    });
    expect(res.progressPercent).toBe(100);
    expect(res.hasValidVersion).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
