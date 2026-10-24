import { describe, expect, it } from 'vitest';

import { auditConstraintSummaryWidgetGovernance } from '../ConstraintSummaryWidget';

describe('auditConstraintSummaryWidgetGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditConstraintSummaryWidgetGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('constraint-summary-widget');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
