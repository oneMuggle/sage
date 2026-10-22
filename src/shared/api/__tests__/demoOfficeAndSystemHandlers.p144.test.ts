import { describe, expect, it } from 'vitest';

import { auditDemoOfficeAndSystemHandlersGovernance } from '../demoOfficeAndSystemHandlers';

describe('demoOfficeAndSystemHandlers P144 governance audit', () => {
  it('returns healthy defaults for demo office and system handlers governance', () => {
    const res = auditDemoOfficeAndSystemHandlersGovernance();
    expect(res.module).toBe('src/shared/api/demoOfficeAndSystemHandlers.ts');
    expect(res.phase).toBe('P144');
    expect(res.registeredHandlerCount).toBe(12);
    expect(res.supportsOfflineFallback).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes registeredHandlerCount and fallback flag', () => {
    const res = auditDemoOfficeAndSystemHandlersGovernance({
      registeredHandlerCount: 15.6,
      supportsOfflineFallback: false,
    });
    expect(res.registeredHandlerCount).toBe(15);
    expect(res.supportsOfflineFallback).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
