import { describe, expect, it } from 'vitest';

import {
  auditUseSessionMemoryPauseGovernance,
  formatSessionMemoryPauseJson,
  formatSessionMemoryPauseSummary,
} from '../useSessionMemoryPause';

describe('useSessionMemoryPause Phase P161 governance audit', () => {
  it('audits useSessionMemoryPause governance metadata', () => {
    const audit = auditUseSessionMemoryPauseGovernance('sess-p161', 'privacy-governance');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useSessionMemoryPause.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('privacy-governance');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseSessionMemoryPause Governance');
  });

  it('preserves session memory pause summary and JSON helpers', () => {
    const ids = new Set(['s1']);
    expect(formatSessionMemoryPauseSummary(ids, 's1', false)).toContain('paused');
    expect(formatSessionMemoryPauseJson(ids, 's1', false)).toContain('maxSessions');
    const fallback = auditUseSessionMemoryPauseGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
