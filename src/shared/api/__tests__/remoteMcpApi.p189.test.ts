import { describe, expect, it } from 'vitest';

import { auditRemoteMcpApiGovernance } from '../remoteMcpApi';

describe('auditRemoteMcpApiGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditRemoteMcpApiGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('remote-mcp-api');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
