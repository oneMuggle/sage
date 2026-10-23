import { describe, expect, it } from 'vitest';

import {
  FIND_HIGHLIGHT,
  SEARCH_HIT_HIGHLIGHT,
  auditTextHighlightGovernance,
  buildTextHighlightAuditJson,
} from '../textHighlight';

describe('textHighlight Phase P160 governance audit', () => {
  it('audits textHighlight governance metadata', () => {
    const audit = auditTextHighlightGovernance('sess-p160', 'search-navigation');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/textHighlight.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('search-navigation');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 TextHighlight Governance');
  });

  it('preserves highlight constants and audit JSON helper', () => {
    expect(SEARCH_HIT_HIGHLIGHT).toBe('sage-search-hit');
    expect(FIND_HIGHLIGHT).toBe('sage-find');
    expect(buildTextHighlightAuditJson(null, 'sage')).toContain('sage');
    const fallback = auditTextHighlightGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
