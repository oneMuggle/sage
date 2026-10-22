import { describe, expect, it } from 'vitest';

import {
  auditAttachmentUpload,
  exportAttachmentUploadAuditJson,
} from '../AttachmentUpload';

describe('AttachmentUpload audit diagnostics', () => {
  it('audits attachment count and uploading state', () => {
    const def = auditAttachmentUpload();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/features/send-message/AttachmentUpload.tsx');
    expect(def.attachmentCount).toBe(0);
    expect(def.isUploading).toBe(false);
    expect(def.acceptedTypesCount).toBeGreaterThan(0);

    const busy = auditAttachmentUpload(-3, true);
    expect(busy.attachmentCount).toBe(0);
    expect(busy.isUploading).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportAttachmentUploadAuditJson(2, true));
    expect(parsed.componentName).toBe('AttachmentUpload');
    expect(parsed.attachmentCount).toBe(2);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
