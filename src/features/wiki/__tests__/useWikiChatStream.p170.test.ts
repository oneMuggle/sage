import { describe, expect, it } from 'vitest';

import { auditUseWikiChatStreamGovernance } from '../useWikiChatStream';

describe('auditUseWikiChatStreamGovernance (P170)', () => {
  it('returns compliant governance audit metadata for useWikiChatStream', () => {
    const report = auditUseWikiChatStreamGovernance();
    expect(report.module).toBe('src/features/wiki/useWikiChatStream.ts');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('wiki');
    expect(report.cancelsStreamOnCleanup).toBe(true);
    expect(report.tracksCitationsAndSources).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
