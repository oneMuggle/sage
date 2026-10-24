import { describe, expect, it } from 'vitest';

import { auditTaskTreeGovernance } from '../taskTree';

describe('auditTaskTreeGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditTaskTreeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('task-tree');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
