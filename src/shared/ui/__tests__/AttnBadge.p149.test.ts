import { describe, expect, it } from 'vitest';

import { auditAttnBadgeGovernance } from '../AttnBadge';

describe('AttnBadge P149 governance audit', () => {
  it('returns healthy defaults for AttnBadge governance', () => {
    const res = auditAttnBadgeGovernance();
    expect(res.module).toBe('src/shared/ui/AttnBadge.tsx');
    expect(res.phase).toBe('P149');
    expect(res.count).toBe(0);
    expect(res.displayLabel).toBe('0');
    expect(res.healthy).toBe(true);
  });

  it('caps displayLabel at 99+ when count exceeds ATTN_BADGE_MAX_DISPLAY', () => {
    const res = auditAttnBadgeGovernance({ count: 150 });
    expect(res.count).toBe(150);
    expect(res.displayLabel).toBe('99+');
    expect(res.healthy).toBe(true);
  });
});
