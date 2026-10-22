import { describe, expect, it } from 'vitest';

import { auditDropdownMenuGovernance } from '../DropdownMenu/DropdownMenu';

describe('DropdownMenu P149 governance audit', () => {
  it('returns healthy defaults for DropdownMenu governance', () => {
    const res = auditDropdownMenuGovernance();
    expect(res.module).toBe('src/shared/ui/DropdownMenu/DropdownMenu.tsx');
    expect(res.phase).toBe('P149');
    expect(res.itemCount).toBe(4);
    expect(res.open).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when itemCount is 0', () => {
    const res = auditDropdownMenuGovernance({
      itemCount: 0,
      open: true,
    });
    expect(res.itemCount).toBe(0);
    expect(res.open).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
