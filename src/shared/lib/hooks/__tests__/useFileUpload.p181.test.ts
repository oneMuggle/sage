import { describe, expect, it } from 'vitest';

import {
  auditUseFileUploadGovernance,
  formatFileUploadJson,
  formatFileUploadSummary,
} from '../useFileUpload';

describe('useFileUpload P181 governance audit', () => {
  it('audits useFileUpload governance contract and upload summary formatters', () => {
    const raw = auditUseFileUploadGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.hooks.use_file_upload.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.supportedExtensionCount).toBeGreaterThan(5);
    expect(formatFileUploadSummary([], [], false)).toBe('upload: 0 files · 0 images · 0 B · idle');
    expect(JSON.parse(formatFileUploadJson([], [], true)).isDragOver).toBe(true);
  });
});
