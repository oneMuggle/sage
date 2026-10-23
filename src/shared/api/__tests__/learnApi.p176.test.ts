import { describe, expect, it } from 'vitest';

import {
  auditLearnApiGovernance,
  formatLearnTriggerJson,
  formatLearnTriggerSummary,
} from '../learnApi';

describe('learnApi P176 governance audit', () => {
  it('audits learnApi governance contract and trigger formatters', () => {
    const raw = auditLearnApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.learn_api.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.ipcCommand).toBe('trigger_learn');
    expect(formatLearnTriggerSummary('s1', 'hello')).toContain('session=s1');
    expect(JSON.parse(formatLearnTriggerJson('s1', 'hello')).sessionId).toBe('s1');
  });
});
