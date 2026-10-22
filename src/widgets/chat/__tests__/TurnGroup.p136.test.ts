import { describe, expect, it } from 'vitest';

import {
  evaluateTurnGroupAudit,
  exportTurnGroupAuditJson,
} from '../TurnGroup';

describe('TurnGroup audit diagnostics (Phase P136)', () => {
  it('validates populated conversation turn group', () => {
    const report = evaluateTurnGroupAudit({
      turnId: 'turn-10',
      messageCount: 2,
      toolCallCount: 3,
      isStreaming: false,
    });
    expect(report.healthy).toBe(true);
    expect(report.messageCount).toBe(2);
  });

  it('flags missing turn id and empty turn group', () => {
    const parsed = JSON.parse(
      exportTurnGroupAuditJson({
        turnId: ' ',
        messageCount: 0,
        toolCallCount: 0,
        isStreaming: true,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_turn_id');
    expect(parsed.issueCodes).toContain('empty_turn_group');
  });
});
