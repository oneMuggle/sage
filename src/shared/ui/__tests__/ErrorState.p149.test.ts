import { describe, expect, it } from 'vitest';

import { auditErrorStateGovernance } from '../ErrorState/ErrorState';

describe('ErrorState P149 governance audit', () => {
  it('returns healthy defaults for ErrorState governance', () => {
    const res = auditErrorStateGovernance();
    expect(res.module).toBe('src/shared/ui/ErrorState/ErrorState.tsx');
    expect(res.phase).toBe('P149');
    expect(res.hasRetryCallback).toBe(true);
    expect(res.messageLength).toBe(24);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when messageLength is 0', () => {
    const res = auditErrorStateGovernance({
      hasRetryCallback: false,
      messageLength: 0,
    });
    expect(res.hasRetryCallback).toBe(false);
    expect(res.messageLength).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
