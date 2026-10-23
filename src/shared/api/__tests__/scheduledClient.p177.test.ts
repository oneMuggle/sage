import { describe, expect, it } from 'vitest';

import {
  auditScheduledClientGovernance,
  formatScheduledTaskJson,
  formatScheduledTaskSummary,
} from '../scheduledClient';

describe('scheduledClient P177 governance audit', () => {
  it('audits scheduledClient governance contract and task formatters', () => {
    const raw = auditScheduledClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.scheduled_client.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.methods).toContain('runNow');
    const sample = {
      id: 't1',
      name: 'Job',
      type: 'recurring' as const,
      enabled: true,
      session_id: 's1',
    };
    expect(formatScheduledTaskSummary(sample)).toBe('t1 · Job · recurring · enabled');
    expect(JSON.parse(formatScheduledTaskJson(sample)).id).toBe('t1');
  });
});
