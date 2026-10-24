import { describe, expect, it } from 'vitest';

import { auditForkTreeGovernance } from '../forkTree';

describe('auditForkTreeGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditForkTreeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('fork-tree');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
