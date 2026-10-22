import { describe, expect, it } from 'vitest';

import { auditSettingsValidationGovernance } from '../settingsValidation';

describe('settingsValidation P155 governance audit', () => {
  it('returns healthy defaults for settingsValidation governance', () => {
    const res = auditSettingsValidationGovernance();
    expect(res.module).toBe('src/entities/setting/settingsValidation.ts');
    expect(res.phase).toBe('P155');
    expect(res.errorCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when errorCount is greater than 0', () => {
    const res = auditSettingsValidationGovernance({ errorCount: 3 });
    expect(res.errorCount).toBe(3);
    expect(res.healthy).toBe(false);
  });
});
