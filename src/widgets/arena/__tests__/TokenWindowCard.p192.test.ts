import { describe, expect, it } from 'vitest';

import { auditTokenWindowCardGovernance } from '../TokenWindowCard';

describe('auditTokenWindowCardGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditTokenWindowCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('token-window-card');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
