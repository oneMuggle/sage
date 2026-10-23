import { describe, expect, it } from 'vitest';

import {
  auditUseCountdownGovernance,
  formatCountdownJson,
  formatCountdownSummary,
} from '../useCountdown';

describe('useCountdown P180 governance audit', () => {
  it('audits useCountdown governance contract and countdown formatters', () => {
    const raw = auditUseCountdownGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_countdown.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.tickingSummary).toContain('ticking · 3/5s');
    expect(formatCountdownSummary(5, 0, 'r1')).toBe('done · 0/5s · key=r1');
    expect(JSON.parse(formatCountdownJson(5, 2, 'r1')).active).toBe(true);
  });
});
