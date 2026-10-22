import { describe, expect, it } from 'vitest';

import { auditSelectGovernance } from '../Select/Select';

describe('Select P149 governance audit', () => {
  it('returns healthy defaults for Select governance', () => {
    const res = auditSelectGovernance();
    expect(res.module).toBe('src/shared/ui/Select/Select.tsx');
    expect(res.phase).toBe('P149');
    expect(res.optionCount).toBe(5);
    expect(res.disabled).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when optionCount is 0', () => {
    const res = auditSelectGovernance({
      optionCount: 0,
      disabled: true,
    });
    expect(res.optionCount).toBe(0);
    expect(res.disabled).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
