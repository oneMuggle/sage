import { describe, expect, it } from 'vitest';

import { auditAgentDetailsGovernance } from '../AgentDetails';

describe('auditAgentDetailsGovernance (Phase P184)', () => {
  it('returns deterministic P184 governance audit payload', () => {
    const payload = JSON.parse(auditAgentDetailsGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('agent-details');
    expect(payload.phase).toBe('P184');
    expect(payload.audited).toBe(true);
  });
});
