import { describe, expect, it } from 'vitest';

import {
  auditReadAloudStoreGovernance,
  buildReadAloudStoreAuditJson,
} from '../readAloudStore';

describe('readAloudStore Phase P160 governance audit', () => {
  it('audits readAloudStore governance metadata', () => {
    const audit = auditReadAloudStoreGovernance('sess-p160', 'accessibility');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/readAloudStore.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('accessibility');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 ReadAloudStore Governance');
  });

  it('preserves readAloudStore audit JSON helper', () => {
    expect(buildReadAloudStoreAuditJson()).toContain('isSpeaking');
    const fallback = auditReadAloudStoreGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
