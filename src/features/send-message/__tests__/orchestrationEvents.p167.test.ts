import { describe, expect, it } from 'vitest';

import { auditOrchestrationEventsGovernance } from '../orchestrationEvents';

describe('auditOrchestrationEventsGovernance (P167)', () => {
  it('returns compliant governance audit metadata for orchestrationEvents', () => {
    const report = auditOrchestrationEventsGovernance();
    expect(report.module).toBe('src/features/send-message/orchestrationEvents.ts');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('send-message');
    expect(report.supportsRunToBoardRestore).toBe(true);
    expect(report.tracksRetryAndTokenTelemetry).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
