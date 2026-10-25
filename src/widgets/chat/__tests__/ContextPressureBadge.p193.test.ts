import { describe, expect, it } from 'vitest';

import { auditContextPressureBadgeGovernance } from '../ContextPressureBadge';

describe('auditContextPressureBadgeGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditContextPressureBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('context-pressure-badge');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
