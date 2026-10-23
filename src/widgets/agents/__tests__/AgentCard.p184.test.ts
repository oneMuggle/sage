import { describe, expect, it } from 'vitest';

import { auditAgentCardGovernance } from '../AgentCard';

describe('auditAgentCardGovernance (Phase P184)', () => {
  it('returns deterministic P184 governance audit payload', () => {
    const payload = JSON.parse(auditAgentCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('agent-card');
    expect(payload.phase).toBe('P184');
    expect(payload.audited).toBe(true);
  });
});
