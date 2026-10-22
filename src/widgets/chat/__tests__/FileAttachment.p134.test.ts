import { describe, expect, it } from 'vitest';

import {
  evaluateFileAttachmentAudit,
  exportFileAttachmentAuditJson,
} from '../FileAttachment';

describe('FileAttachment audit diagnostics (Phase P134)', () => {
  it('accepts valid file attachment within size limit', () => {
    const report = evaluateFileAttachmentAudit({
      fileName: 'report.pdf',
      fileSizeBytes: 1024,
      mimeType: 'application/pdf',
      maxAllowedBytes: 1048576,
    });
    expect(report.healthy).toBe(true);
    expect(report.withinSizeLimit).toBe(true);
  });

  it('flags oversized or unnamed file attachment', () => {
    const parsed = JSON.parse(
      exportFileAttachmentAuditJson({
        fileName: ' ',
        fileSizeBytes: 5000,
        mimeType: '',
        maxAllowedBytes: 1000,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_attachment_filename');
    expect(parsed.issueCodes).toContain('attachment_exceeds_size_limit');
  });
});
