import { describe, expect, it } from 'vitest';

import {
  TURN_PREVIEW_MAX_CHARS,
  auditUseConversationTurnsGovernance,
  formatConversationTurnsJson,
} from '../useConversationTurns';

describe('useConversationTurns Phase P161 governance audit', () => {
  it('audits useConversationTurns governance metadata', () => {
    const audit = auditUseConversationTurnsGovernance('sess-p161', 'navigation');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useConversationTurns.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('navigation');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseConversationTurns Governance');
  });

  it('preserves turn preview constant and JSON helper', () => {
    expect(TURN_PREVIEW_MAX_CHARS).toBe(48);
    expect(formatConversationTurnsJson([{ index: 1, messageId: 'm1', preview: 'hello' }])).toContain('m1');
    const fallback = auditUseConversationTurnsGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
