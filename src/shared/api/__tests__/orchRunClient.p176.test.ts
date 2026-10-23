import { describe, expect, it } from 'vitest';

import {
  auditOrchRunClientGovernance,
  formatOrchRunDetailJson,
  formatOrchRunDetailSummary,
} from '../orchRunClient';

describe('orchRunClient P176 governance audit', () => {
  it('audits orchRunClient governance contract and run detail formatters', () => {
    const raw = auditOrchRunClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.orch_run_client.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.methods).toContain('rerunFailed');
    const detail = {
      run_id: 'r1',
      session_id: 's1',
      status: 'completed',
      created_at: 1000,
      plan: [],
      tasks: [],
    };
    expect(formatOrchRunDetailSummary(detail)).toBe('r1 · completed · plan=0 · tasks=0');
    expect(JSON.parse(formatOrchRunDetailJson(detail)).runId).toBe('r1');
  });
});
