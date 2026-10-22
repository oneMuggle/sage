import { describe, expect, it } from 'vitest';

import { auditLiveDotGovernance } from '../LiveDot';

describe('LiveDot P149 governance audit', () => {
  it('returns healthy defaults for LiveDot governance', () => {
    const res = auditLiveDotGovernance();
    expect(res.module).toBe('src/shared/ui/LiveDot.tsx');
    expect(res.phase).toBe('P149');
    expect(res.liveState).toBe('idle');
    expect(res.pulseEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes liveState and pulseEnabled', () => {
    const res = auditLiveDotGovernance({
      liveState: 'working',
      pulseEnabled: false,
    });
    expect(res.liveState).toBe('working');
    expect(res.pulseEnabled).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
