import { describe, expect, it } from 'vitest';

import { auditQueryClientProviderGovernance } from '../QueryClientProvider';

describe('QueryClientProvider P151 governance audit', () => {
  it('returns healthy defaults for QueryClientProvider governance', () => {
    const res = auditQueryClientProviderGovernance();
    expect(res.module).toBe('src/app/providers/QueryClientProvider.tsx');
    expect(res.phase).toBe('P151');
    expect(res.staleTimeMs).toBe(60000);
    expect(res.retryCount).toBe(1);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when staleTimeMs is below 1000', () => {
    const res = auditQueryClientProviderGovernance({
      staleTimeMs: 100,
      retryCount: 25,
    });
    expect(res.staleTimeMs).toBe(100);
    expect(res.retryCount).toBe(10);
    expect(res.healthy).toBe(false);
  });
});
