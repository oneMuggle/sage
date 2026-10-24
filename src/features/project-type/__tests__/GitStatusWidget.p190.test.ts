import { describe, expect, it } from 'vitest';

import { auditGitStatusWidgetGovernance } from '../GitStatusWidget';

describe('auditGitStatusWidgetGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditGitStatusWidgetGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('git-status-widget');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
