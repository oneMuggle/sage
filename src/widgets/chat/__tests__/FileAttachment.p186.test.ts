import { describe, expect, it } from 'vitest';

import { auditFileAttachmentGovernance } from '../FileAttachment';

describe('auditFileAttachmentGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditFileAttachmentGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('file-attachment');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
