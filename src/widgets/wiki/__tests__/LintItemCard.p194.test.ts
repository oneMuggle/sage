import { describe, expect, it } from 'vitest';

import { auditLintItemCardGovernance } from '../LintItemCard';

describe('auditLintItemCardGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditLintItemCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('wiki-lint-item-card');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
