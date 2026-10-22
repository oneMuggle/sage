import { describe, expect, it } from 'vitest';

import {
  QUOTE_SCOPE_ATTR,
  appendQuoteToDraft,
  auditSelectionQuoteGovernance,
  buildSelectionQuoteAuditJson,
} from '../selectionQuote';

describe('selectionQuote Phase P160 governance audit', () => {
  it('audits selectionQuote governance metadata', () => {
    const audit = auditSelectionQuoteGovernance('sess-p160', 'knowledge-base');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/selectionQuote.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('knowledge-base');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 SelectionQuote Governance');
  });

  it('preserves quote helpers and audit JSON serialization', () => {
    expect(QUOTE_SCOPE_ATTR).toBe('data-quote-scope');
    expect(appendQuoteToDraft('draft', 'quoted line')).toContain('quoted line');
    expect(buildSelectionQuoteAuditJson('sample quote')).toContain('isQuotable');
    const fallback = auditSelectionQuoteGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
