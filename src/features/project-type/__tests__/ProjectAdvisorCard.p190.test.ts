import { describe, expect, it } from 'vitest';

import { auditProjectAdvisorCardGovernance } from '../ProjectAdvisorCard';

describe('auditProjectAdvisorCardGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditProjectAdvisorCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-advisor-card');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
