import { describe, expect, it } from 'vitest';

import { auditAttachmentRagClientGovernance } from '../attachmentRagClient';

describe('auditAttachmentRagClientGovernance (Phase P188)', () => {
  it('returns deterministic P188 governance audit payload', () => {
    const payload = JSON.parse(auditAttachmentRagClientGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('attachment-rag-client');
    expect(payload.phase).toBe('P188');
    expect(payload.audited).toBe(true);
  });
});
