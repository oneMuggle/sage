import { describe, expect, it } from 'vitest';

import { auditDemoFixturesSessionsAndAgentsGovernance } from '../demoFixturesSessionsAndAgents';

describe('demoFixturesSessionsAndAgents P144 governance audit', () => {
  it('returns healthy defaults from demo sessions and agents fixtures', () => {
    const res = auditDemoFixturesSessionsAndAgentsGovernance();
    expect(res.module).toBe('src/shared/api/demoFixturesSessionsAndAgents.ts');
    expect(res.phase).toBe('P144');
    expect(res.sessionCount).toBeGreaterThan(0);
    expect(res.agentCount).toBeGreaterThan(0);
    expect(res.scheduledTaskCount).toBeGreaterThanOrEqual(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes sessionCount and agentCount', () => {
    const res = auditDemoFixturesSessionsAndAgentsGovernance({
      sessionCount: 4.9,
      agentCount: 0,
      scheduledTaskCount: 2.3,
    });
    expect(res.sessionCount).toBe(4);
    expect(res.agentCount).toBe(0);
    expect(res.scheduledTaskCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
