import { describe, expect, it } from 'vitest';

import {
  evaluateTerminalPanelAudit,
  exportTerminalPanelAuditJson,
} from '../TerminalPanel';

describe('TerminalPanel audit diagnostics (Phase P135)', () => {
  it('validates active terminal session within buffer cap', () => {
    const report = evaluateTerminalPanelAudit({
      sessionCount: 2,
      activeSessionId: 'term-1',
      bufferLineCount: 400,
      maxBufferLines: 2000,
    });
    expect(report.healthy).toBe(true);
    expect(report.withinBufferCap).toBe(true);
  });

  it('flags missing active session and buffer overflow', () => {
    const parsed = JSON.parse(
      exportTerminalPanelAuditJson({
        sessionCount: 1,
        activeSessionId: ' ',
        bufferLineCount: 5000,
        maxBufferLines: 1000,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_active_terminal_session_id');
    expect(parsed.issueCodes).toContain('terminal_buffer_overflow');
  });
});
