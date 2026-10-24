import { describe, expect, it } from 'vitest';

import { auditAttachmentRagConfigGovernance } from '../attachmentRagConfig';

describe('auditAttachmentRagConfigGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditAttachmentRagConfigGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('attachment-rag-config');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
