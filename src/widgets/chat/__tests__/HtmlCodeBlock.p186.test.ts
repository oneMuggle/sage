import { describe, expect, it } from 'vitest';

import { auditHtmlCodeBlockGovernance } from '../HtmlCodeBlock';

describe('auditHtmlCodeBlockGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditHtmlCodeBlockGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('html-code-block');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
