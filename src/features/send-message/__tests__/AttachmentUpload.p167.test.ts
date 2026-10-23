import { describe, expect, it } from 'vitest';

import { auditAttachmentUploadGovernance } from '../AttachmentUpload';

describe('auditAttachmentUploadGovernance (P167)', () => {
  it('returns compliant governance audit metadata for AttachmentUpload', () => {
    const report = auditAttachmentUploadGovernance();
    expect(report.module).toBe('src/features/send-message/AttachmentUpload.tsx');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('send-message');
    expect(report.supportsMultiFileSelection).toBe(true);
    expect(report.filtersAcceptedMimeExtensions).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
