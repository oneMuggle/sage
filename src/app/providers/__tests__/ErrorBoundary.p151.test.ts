import { describe, expect, it } from 'vitest';

import { auditErrorBoundaryGovernance } from '../ErrorBoundary';

describe('ErrorBoundary P151 governance audit', () => {
  it('returns healthy defaults for ErrorBoundary governance', () => {
    const res = auditErrorBoundaryGovernance();
    expect(res.module).toBe('src/app/providers/ErrorBoundary.tsx');
    expect(res.phase).toBe('P151');
    expect(res.hasError).toBe(false);
    expect(res.recoveryCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditErrorBoundaryGovernance({
      hasError: true,
      recoveryCount: 2,
    });
    expect(res.hasError).toBe(true);
    expect(res.recoveryCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
