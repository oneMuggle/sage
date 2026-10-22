import { describe, expect, it } from 'vitest';

import { auditTabsGovernance } from '../Tabs/Tabs';

describe('Tabs P148 governance audit', () => {
  it('returns healthy defaults for Tabs governance', () => {
    const res = auditTabsGovernance();
    expect(res.module).toBe('src/shared/ui/Tabs/Tabs.tsx');
    expect(res.phase).toBe('P148');
    expect(res.tabCount).toBe(2);
    expect(res.activeValue).toBe('overview');
    expect(res.healthy).toBe(true);
  });

  it('normalizes tabCount and activeValue', () => {
    const res = auditTabsGovernance({
      tabCount: 4.8,
      activeValue: ' settings ',
    });
    expect(res.tabCount).toBe(4);
    expect(res.activeValue).toBe('settings');
    expect(res.healthy).toBe(true);
  });
});
