import { describe, expect, it } from 'vitest';

import {
  auditUseConversationOutlineGovernance,
  formatConversationOutlineJson,
  formatConversationOutlineSummary,
} from '../useConversationOutline';

describe('useConversationOutline Phase P161 governance audit', () => {
  it('audits useConversationOutline governance metadata', () => {
    const audit = auditUseConversationOutlineGovernance('sess-p161', 'documentation');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useConversationOutline.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('documentation');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseConversationOutline Governance');
  });

  it('preserves outline summary and JSON helpers', () => {
    const items = [{ text: 'Overview', messageId: 'm1', level: 2 as const }];
    expect(formatConversationOutlineSummary(items, false)).toContain('1 headings');
    expect(formatConversationOutlineJson(items, false)).toContain('Overview');
    const fallback = auditUseConversationOutlineGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
