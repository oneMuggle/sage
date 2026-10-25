import { describe, expect, it } from 'vitest';

import { auditActivityPanelGovernance } from '../ActivityPanel';

describe('auditActivityPanelGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditActivityPanelGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('wiki-activity-panel');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
