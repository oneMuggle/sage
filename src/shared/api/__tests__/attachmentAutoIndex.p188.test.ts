import { describe, expect, it } from 'vitest';

import { auditAttachmentAutoIndexGovernance } from '../attachmentAutoIndex';

describe('auditAttachmentAutoIndexGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditAttachmentAutoIndexGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('attachment-auto-index');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
