import { describe, expect, it } from 'vitest';

import { auditGenerationStatsBadgeGovernance } from '../GenerationStatsBadge';

describe('auditGenerationStatsBadgeGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditGenerationStatsBadgeGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('generation-stats-badge');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
