import { describe, expect, it } from 'vitest';

import { auditContextMeterGovernance } from '../ContextMeter';

describe('auditContextMeterGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditContextMeterGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('context-meter');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
