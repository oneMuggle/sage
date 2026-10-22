import { describe, expect, it } from 'vitest';

import { auditTooltipGovernance } from '../Tooltip/Tooltip';

describe('Tooltip P148 governance audit', () => {
  it('returns healthy defaults for Tooltip governance', () => {
    const res = auditTooltipGovernance();
    expect(res.module).toBe('src/shared/ui/Tooltip/Tooltip.tsx');
    expect(res.phase).toBe('P148');
    expect(res.side).toBe('top');
    expect(res.disabled).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('normalizes side and disabled flag', () => {
    const res = auditTooltipGovernance({
      side: 'bottom',
      disabled: true,
    });
    expect(res.side).toBe('bottom');
    expect(res.disabled).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
