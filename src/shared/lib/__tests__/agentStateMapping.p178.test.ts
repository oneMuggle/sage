import { describe, expect, it } from 'vitest';

import {
  auditAgentStateMappingGovernance,
  formatAgentPhaseJson,
  formatAgentPhaseSummary,
} from '../agentStateMapping';

describe('agentStateMapping P178 governance audit', () => {
  it('audits agentStateMapping governance contract and phase formatters', () => {
    const raw = auditAgentStateMappingGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.agent_state_mapping.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.thinkingSummary).toContain('thinking');
    expect(formatAgentPhaseSummary('done')).toContain('no-phase');
    expect(JSON.parse(formatAgentPhaseJson('thinking')).state).toBe('thinking');
  });
});
