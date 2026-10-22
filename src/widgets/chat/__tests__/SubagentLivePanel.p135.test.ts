import { describe, expect, it } from 'vitest';

import {
  evaluateSubagentLivePanelAudit,
  exportSubagentLivePanelAuditJson,
} from '../SubagentLivePanel';

describe('SubagentLivePanel audit diagnostics (Phase P135)', () => {
  it('validates connected live subagent panel', () => {
    const report = evaluateSubagentLivePanelAudit({
      activeSubagentCount: 2,
      completedSubagentCount: 4,
      failedSubagentCount: 0,
      streamConnected: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags disconnected stream and failed subagents', () => {
    const parsed = JSON.parse(
      exportSubagentLivePanelAuditJson({
        activeSubagentCount: 1,
        completedSubagentCount: 0,
        failedSubagentCount: 2,
        streamConnected: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('subagent_stream_disconnected');
    expect(parsed.issueCodes).toContain('subagent_failures_detected');
  });
});
