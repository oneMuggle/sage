import { describe, expect, it } from 'vitest';

import { auditDemoFixturesCoreGovernance } from '../demoFixturesCore';

describe('demoFixturesCore P144 governance audit', () => {
  it('returns healthy defaults from demo fixtures core collections', () => {
    const res = auditDemoFixturesCoreGovernance();
    expect(res.module).toBe('src/shared/api/demoFixturesCore.ts');
    expect(res.phase).toBe('P144');
    expect(res.memoryCount).toBeGreaterThan(0);
    expect(res.knowledgeDocCount).toBeGreaterThan(0);
    expect(res.skillCount).toBeGreaterThan(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes custom fixture counts', () => {
    const res = auditDemoFixturesCoreGovernance({
      memoryCount: 3.8,
      knowledgeDocCount: 2.1,
      skillCount: 0,
    });
    expect(res.memoryCount).toBe(3);
    expect(res.knowledgeDocCount).toBe(2);
    expect(res.skillCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
