import { describe, expect, it } from 'vitest';

import { auditSharedApiUtilsGovernance } from '../utils';

describe('shared/api/utils P148 governance audit', () => {
  it('returns healthy defaults for shared/api/utils governance', () => {
    const res = auditSharedApiUtilsGovernance();
    expect(res.module).toBe('src/shared/api/utils.ts');
    expect(res.phase).toBe('P148');
    expect(res.validSessionId).toBe(true);
    expect(res.maxRetries).toBe(3);
    expect(res.healthy).toBe(true);
  });

  it('flags invalid sessionId and clamps maxRetries', () => {
    const res = auditSharedApiUtilsGovernance({
      sessionId: 'bad/session/id!',
      maxRetries: 25,
    });
    expect(res.validSessionId).toBe(false);
    expect(res.maxRetries).toBe(10);
    expect(res.healthy).toBe(false);
  });
});
