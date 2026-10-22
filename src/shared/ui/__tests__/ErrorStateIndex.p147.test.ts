import { describe, expect, it } from 'vitest';

import { auditErrorStateBarrelGovernance } from '../ErrorState/index';

describe('ErrorState barrel P147 governance audit', () => {
  it('returns healthy defaults for ErrorState barrel governance', () => {
    const res = auditErrorStateBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/ErrorState/index.ts');
    expect(res.phase).toBe('P147');
    expect(res.hasRetryCallback).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes hasRetryCallback flag', () => {
    const res = auditErrorStateBarrelGovernance({
      hasRetryCallback: false,
    });
    expect(res.hasRetryCallback).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
