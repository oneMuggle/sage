import { describe, expect, it } from 'vitest';

import { auditOrchestrationClientGovernance } from '../orchestrationClient';

describe('orchestrationClient P176 governance audit', () => {
  it('audits orchestrationClient governance contract and board views', () => {
    const raw = auditOrchestrationClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.orchestration_client.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.views).toEqual(['ops_full', 'ui_minimal']);
    expect(parsed.methods).toContain('getBoard');
  });
});
