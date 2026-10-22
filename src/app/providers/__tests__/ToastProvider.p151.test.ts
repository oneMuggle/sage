import { describe, expect, it } from 'vitest';

import { auditToastProviderGovernance } from '../ToastProvider';

describe('ToastProvider P151 governance audit', () => {
  it('returns healthy defaults for ToastProvider governance', () => {
    const res = auditToastProviderGovernance();
    expect(res.module).toBe('src/app/providers/ToastProvider.tsx');
    expect(res.phase).toBe('P151');
    expect(res.maxToasts).toBe(5);
    expect(res.durationMs).toBe(4000);
    expect(res.healthy).toBe(true);
  });

  it('clamps maxToasts and durationMs', () => {
    const res = auditToastProviderGovernance({
      maxToasts: 50,
      durationMs: 200,
    });
    expect(res.maxToasts).toBe(20);
    expect(res.durationMs).toBe(1000);
    expect(res.healthy).toBe(true);
  });
});
