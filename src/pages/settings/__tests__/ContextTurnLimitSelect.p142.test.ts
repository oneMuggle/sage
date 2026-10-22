import { describe, expect, it } from 'vitest';

import { auditContextTurnLimitSelectGovernance } from '../ContextTurnLimitSelect';

describe('ContextTurnLimitSelect P142 governance audit', () => {
  it('returns healthy defaults for ContextTurnLimitSelect governance', () => {
    const res = auditContextTurnLimitSelectGovernance();
    expect(res.module).toBe('src/pages/settings/ContextTurnLimitSelect.tsx');
    expect(res.phase).toBe('P142');
    expect(res.selectedTurnLimit).toBe(20);
    expect(res.minTurnLimit).toBe(0);
    expect(res.maxTurnLimit).toBe(100);
    expect(res.healthy).toBe(true);
  });

  it('clamps selectedTurnLimit within min and max bounds', () => {
    const res = auditContextTurnLimitSelectGovernance({
      selectedTurnLimit: 250,
      minTurnLimit: 5,
      maxTurnLimit: 80,
    });
    expect(res.selectedTurnLimit).toBe(80);
    expect(res.minTurnLimit).toBe(5);
    expect(res.maxTurnLimit).toBe(80);
    expect(res.healthy).toBe(true);
  });
});
