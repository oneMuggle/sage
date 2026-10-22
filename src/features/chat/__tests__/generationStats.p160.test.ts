import { describe, expect, it } from 'vitest';

import {
  auditGenerationStatsGovernance,
  buildGenerationStatsAuditJson,
  formatDuration,
} from '../generationStats';

describe('generationStats Phase P160 governance audit', () => {
  it('audits generationStats governance metadata with explicit session and archetype', () => {
    const audit = auditGenerationStatsGovernance('sess-p160', 'research-lab');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/generationStats.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('research-lab');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 GenerationStats Governance');
  });

  it('preserves duration formatting and audit JSON helpers', () => {
    expect(formatDuration(1500)).toContain('1.5');
    expect(buildGenerationStatsAuditJson()).toContain('hasStats');
    const fallback = auditGenerationStatsGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
    expect(fallback.archetype).toBe('software-engineering');
  });
});
