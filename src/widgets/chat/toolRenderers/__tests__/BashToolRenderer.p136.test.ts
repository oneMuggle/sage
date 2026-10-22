import { describe, expect, it } from 'vitest';

import {
  evaluateBashToolRendererAudit,
  exportBashToolRendererAuditJson,
} from '../BashToolRenderer';

describe('BashToolRenderer audit diagnostics (Phase P136)', () => {
  it('validates clean zero-exit bash command execution', () => {
    const report = evaluateBashToolRendererAudit({
      commandText: 'npm test',
      exitCode: 0,
      outputLineCount: 25,
      timedOut: false,
    });
    expect(report.healthy).toBe(true);
    expect(report.hasCommand).toBe(true);
  });

  it('flags timeout and non-zero exit code', () => {
    const parsed = JSON.parse(
      exportBashToolRendererAuditJson({
        commandText: 'sleep 100',
        exitCode: 124,
        outputLineCount: 0,
        timedOut: true,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('bash_command_timed_out');
    expect(parsed.issueCodes).toContain('non_zero_bash_exit_code');
  });
});
