export { JournalPanel } from './JournalPanel';
export { useJournalTemplates } from './useJournalTemplates';
export function formatJournalBarrelSummary(): string {
  return 'module=features/journal · exports=JournalPanel,useJournalTemplates · count=2';
}

export function formatJournalBarrelJson(): string {
  return JSON.stringify({
    module: 'features/journal',
    exports: ['JournalPanel', 'useJournalTemplates'],
    count: 2,
  });
}

export interface JournalBarrelGovernanceAudit {
  phase: 'P162';
  module: 'src/features/journal/index.ts';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

export function auditJournalBarrelGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): JournalBarrelGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P162',
    module: 'src/features/journal/index.ts',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P162 JournalBarrel Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
