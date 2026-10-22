import { describe, expect, it } from 'vitest';

import {
  auditUseQuoteDraftGovernance,
  formatQuoteDraftInjectionJson,
  formatQuoteDraftInjectionSummary,
} from '../useQuoteDraft';

describe('useQuoteDraft Phase P161 governance audit', () => {
  it('audits useQuoteDraft governance metadata', () => {
    const audit = auditUseQuoteDraftGovernance('sess-p161', 'composer');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useQuoteDraft.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('composer');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseQuoteDraft Governance');
  });

  it('preserves quote draft injection summary and JSON helpers', () => {
    expect(formatQuoteDraftInjectionSummary(null)).toBe('idle');
    expect(formatQuoteDraftInjectionJson({ text: '> hi', nonce: 1, mode: 'append' })).toContain('> hi');
    const fallback = auditUseQuoteDraftGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
