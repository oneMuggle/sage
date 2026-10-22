import { describe, expect, it } from 'vitest';

import { auditOrchEventsGovernance } from '../orchEvents';

describe('orchEvents P145 governance audit', () => {
  it('returns healthy defaults for orchEvents governance', () => {
    const res = auditOrchEventsGovernance();
    expect(res.module).toBe('src/shared/api/orchEvents.ts');
    expect(res.phase).toBe('P145');
    expect(res.connectionStatus).toBe('connected');
    expect(res.activeTaskCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes connectionStatus and activeTaskCount', () => {
    const res = auditOrchEventsGovernance({
      connectionStatus: 'disconnected',
      activeTaskCount: 3.9,
    });
    expect(res.connectionStatus).toBe('disconnected');
    expect(res.activeTaskCount).toBe(3);
    expect(res.healthy).toBe(false);
  });
});
