import { describe, expect, it } from 'vitest';

import {
  evaluateFileWriteToolRendererAudit,
  exportFileWriteToolRendererAuditJson,
} from '../FileWriteToolRenderer';

describe('FileWriteToolRenderer audit diagnostics (Phase P136)', () => {
  it('validates successful file write tool execution', () => {
    const report = evaluateFileWriteToolRendererAudit({
      targetPath: 'src/index.ts',
      bytesWritten: 256,
      createdNewFile: false,
      succeeded: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.bytesWritten).toBe(256);
  });

  it('flags missing target path and failed write', () => {
    const parsed = JSON.parse(
      exportFileWriteToolRendererAuditJson({
        targetPath: ' ',
        bytesWritten: 0,
        createdNewFile: true,
        succeeded: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_file_write_target_path');
    expect(parsed.issueCodes).toContain('file_write_operation_failed');
  });
});
