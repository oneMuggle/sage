import { describe, expect, it } from 'vitest';

import {
  auditUseElapsedSecondsGovernance,
  formatElapsedSecondsJson,
  formatElapsedSecondsSummary,
} from '../useElapsedSeconds';

describe('useElapsedSeconds P180 governance audit', () => {
  it('audits useElapsedSeconds governance contract and elapsed formatters', () => {
    const raw = auditUseElapsedSecondsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_elapsed_seconds.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.activeSummary).toBe('active=true · elapsed=12s');
    expect(formatElapsedSecondsSummary(false, 0)).toBe('active=false · elapsed=0s');
    expect(JSON.parse(formatElapsedSecondsJson(true, 7)).elapsedSeconds).toBe(7);
  });
});
