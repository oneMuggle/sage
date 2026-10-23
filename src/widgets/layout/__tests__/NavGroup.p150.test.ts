import { describe, expect, it } from 'vitest';

import { auditNavGroupGovernance } from '../NavGroup';

describe('NavGroup P150 governance audit', () => {
  it('returns healthy defaults for NavGroup governance', () => {
    const res = auditNavGroupGovernance();
    expect(res.module).toBe('src/widgets/layout/NavGroup.tsx');
    expect(res.phase).toBe('P150');
    expect(res.itemCount).toBe(4);
    expect(res.collapsed).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when itemCount is 0', () => {
    const res = auditNavGroupGovernance({ itemCount: 0, collapsed: true });
    expect(res.itemCount).toBe(0);
    expect(res.collapsed).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
