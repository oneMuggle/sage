import { describe, expect, it } from 'vitest';

import {
  auditUseBtwCommandGovernance,
  formatBtwCommandStateJson,
  formatBtwCommandStateSummary,
} from '../useBtwCommand';

describe('useBtwCommand Phase P161 governance audit', () => {
  it('audits useBtwCommand governance metadata', () => {
    const audit = auditUseBtwCommandGovernance('sess-p161', 'research-lab');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useBtwCommand.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('research-lab');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseBtwCommand Governance');
  });

  it('preserves state summary and JSON helpers', () => {
    const state = { isOpen: true, question: 'why?', answer: 'because', isLoading: false };
    expect(formatBtwCommandStateSummary(state)).toContain('open');
    expect(formatBtwCommandStateJson(state)).toContain('why?');
    const fallback = auditUseBtwCommandGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
