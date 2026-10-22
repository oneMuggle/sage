import { describe, expect, it } from 'vitest';

import { auditWikiLintStoreGovernance } from '../lint-store';

describe('wiki lint-store P156 governance audit', () => {
  it('returns healthy defaults for wiki lint-store governance', () => {
    const res = auditWikiLintStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/lint-store.ts');
    expect(res.phase).toBe('P156');
    expect(res.lintItemCount).toBe(0);
    expect(res.unresolvedErrorCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when unresolvedErrorCount is greater than 0', () => {
    const res = auditWikiLintStoreGovernance({
      lintItemCount: 5,
      unresolvedErrorCount: 2,
    });
    expect(res.lintItemCount).toBe(5);
    expect(res.unresolvedErrorCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
