import { describe, expect, it } from 'vitest';

import { auditMessageMarkdownPartsGovernance } from '../MessageMarkdownParts';

describe('auditMessageMarkdownPartsGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditMessageMarkdownPartsGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('message-markdown-parts');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
