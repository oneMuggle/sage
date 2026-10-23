import { describe, expect, it } from 'vitest';

import { auditTabsBarrelGovernance } from '../Tabs/index';

describe('Tabs barrel P148 governance audit', () => {
  it('returns healthy defaults for Tabs barrel governance', () => {
    const res = auditTabsBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/Tabs/index.ts');
    expect(res.phase).toBe('P148');
    expect(res.exportedCount).toBe(4);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when exportedCount is below 4', () => {
    const res = auditTabsBarrelGovernance({ exportedCount: 2 });
    expect(res.exportedCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
