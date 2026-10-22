import { describe, expect, it } from 'vitest';

import {
  evaluateDocumentPreviewAudit,
  exportDocumentPreviewAuditJson,
} from '../DocumentPreview';

describe('DocumentPreview audit diagnostics (Phase P136)', () => {
  it('validates ready multi-page document preview', () => {
    const report = evaluateDocumentPreviewAudit({
      documentPath: '/docs/spec.pdf',
      format: 'PDF',
      pageCount: 4,
      previewReady: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedFormat).toBe('pdf');
  });

  it('flags missing path and unready preview', () => {
    const parsed = JSON.parse(
      exportDocumentPreviewAuditJson({
        documentPath: ' ',
        format: '',
        pageCount: 0,
        previewReady: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_document_path');
    expect(parsed.issueCodes).toContain('document_preview_not_ready');
  });
});
