import { describe, expect, it } from 'vitest';

import { auditToolCallEnvelopeGovernance } from '../toolCallEnvelope';

describe('auditToolCallEnvelopeGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditToolCallEnvelopeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('tool-call-envelope');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
