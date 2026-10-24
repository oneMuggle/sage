import { describe, expect, it } from 'vitest';

import { auditProjectOverviewWidgetsGovernance } from '../ProjectOverviewWidgets';

describe('auditProjectOverviewWidgetsGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditProjectOverviewWidgetsGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-overview-widgets');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
