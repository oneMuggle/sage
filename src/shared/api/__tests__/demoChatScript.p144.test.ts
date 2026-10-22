import { describe, expect, it } from 'vitest';

import { auditDemoChatScriptGovernance } from '../demoChatScript';

describe('demoChatScript P144 governance audit', () => {
  it('returns healthy defaults for demoChatScript governance', () => {
    const res = auditDemoChatScriptGovernance();
    expect(res.module).toBe('src/shared/api/demoChatScript.ts');
    expect(res.phase).toBe('P144');
    expect(res.scriptStepCount).toBe(6);
    expect(res.chunkDelayMs).toBe(20);
    expect(res.healthy).toBe(true);
  });

  it('normalizes scriptStepCount and chunkDelayMs', () => {
    const res = auditDemoChatScriptGovernance({
      scriptStepCount: 0,
      chunkDelayMs: -5,
    });
    expect(res.scriptStepCount).toBe(0);
    expect(res.chunkDelayMs).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
