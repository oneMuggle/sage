import { describe, expect, it } from 'vitest';

import { auditSessionUsageBadgeGovernance } from '../SessionUsageBadge';

describe('auditSessionUsageBadgeGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditSessionUsageBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('session-usage-badge');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
