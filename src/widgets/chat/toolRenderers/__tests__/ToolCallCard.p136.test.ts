import { describe, expect, it } from 'vitest';

import {
  evaluateToolCallCardAudit,
  exportToolCallCardAuditJson,
} from '../ToolCallCard';

describe('ToolCallCard audit diagnostics (Phase P136)', () => {
  it('validates completed tool call card', () => {
    const report = evaluateToolCallCardAudit({
      toolName: 'read_file',
      callId: 'call-99',
      status: 'completed',
      durationMs: 140,
    });
    expect(report.healthy).toBe(true);
    expect(report.durationMs).toBe(140);
  });

  it('flags failed tool call and missing metadata', () => {
    const parsed = JSON.parse(
      exportToolCallCardAuditJson({
        toolName: '',
        callId: ' ',
        status: 'failed',
        durationMs: 50,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_tool_name');
    expect(parsed.issueCodes).toContain('missing_tool_call_id');
    expect(parsed.issueCodes).toContain('tool_call_failed');
  });
});
