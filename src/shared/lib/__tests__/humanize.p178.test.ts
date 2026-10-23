import { describe, expect, it } from 'vitest';

import {
  auditHumanizeGovernance,
  formatHumanizedToolJson,
  formatHumanizedToolSummary,
} from '../humanize';

describe('humanize P178 governance audit', () => {
  it('audits humanize governance contract and tool call humanizer', () => {
    const raw = auditHumanizeGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.humanize.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.mcpSample).toContain('external');
    expect(formatHumanizedToolSummary('mcp__slack__post', {})).toContain('Use slack · post');
    expect(JSON.parse(formatHumanizedToolJson('runtime_exec', { language: 'python' })).scope).toBe(
      'local',
    );
  });
});
