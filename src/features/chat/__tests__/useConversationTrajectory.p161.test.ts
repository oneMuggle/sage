import { describe, expect, it } from 'vitest';

import {
  TRAJECTORY_PREVIEW_MAX_CHARS,
  auditUseConversationTrajectoryGovernance,
  formatTrajectorySummaryJson,
} from '../useConversationTrajectory';

describe('useConversationTrajectory Phase P161 governance audit', () => {
  it('audits useConversationTrajectory governance metadata', () => {
    const audit = auditUseConversationTrajectoryGovernance('sess-p161', 'observability');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useConversationTrajectory.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('observability');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseConversationTrajectory Governance');
  });

  it('preserves trajectory preview constant and JSON summary helper', () => {
    expect(TRAJECTORY_PREVIEW_MAX_CHARS).toBe(60);
    const json = formatTrajectorySummaryJson({
      totalEntries: 2,
      totalToolCalls: 1,
      totalInputTokens: 100,
      totalOutputTokens: 50,
      totalLatencyMs: 420,
      maxLatencyMs: 300,
    });
    expect(json).toContain('totalToolCalls');
    const fallback = auditUseConversationTrajectoryGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
