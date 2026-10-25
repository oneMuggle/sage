import { describe, expect, it } from 'vitest';

import { auditProjectBadgeGovernance } from '../ProjectBadge';

describe('auditProjectBadgeGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditProjectBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-badge');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
