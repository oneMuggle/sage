import { describe, expect, it } from 'vitest';

import {
  auditUseMessageJumpGovernance,
  formatMessageJumpJson,
  formatMessageJumpSummary,
} from '../useMessageJump';

describe('useMessageJump Phase P161 governance audit', () => {
  it('audits useMessageJump governance metadata', () => {
    const audit = auditUseMessageJumpGovernance('sess-p161', 'navigation');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useMessageJump.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('navigation');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseMessageJump Governance');
  });

  it('preserves message jump summary and JSON helpers', () => {
    expect(formatMessageJumpSummary(20, 'msg-1', 50)).toContain('msg-1');
    expect(formatMessageJumpJson(20, 'msg-1', 50)).toContain('flashDurationMs');
    const fallback = auditUseMessageJumpGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
