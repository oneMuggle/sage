// src/features/chat/index.ts
export { AtFileMenu } from './AtFileMenu';
export { AtEntityMenu } from './AtEntityMenu';
export { getEntityKindSuggestions, parseEntityRefQuery } from './entityRefs';
export { useAtFileQuery } from './useAtFileQuery';
export { useBtwCommand } from './useBtwCommand';
export { BtwOverlay } from './BtwOverlay';
export { useBtwState } from '../../entities/chat/btwState';
export function formatChatFeatureBarrelSummary(): string {
  return 'module=features/chat · exports=8 · includes=AtFileMenu,AtEntityMenu,BtwOverlay';
}

export function formatChatFeatureBarrelJson(): string {
  return JSON.stringify({
    module: 'features/chat',
    exportCount: 8,
    components: ['AtFileMenu', 'AtEntityMenu', 'BtwOverlay'],
  });
}

export interface ChatFeatureBarrelGovernanceAudit {
  phase: 'P160';
  module: 'src/features/chat/index.ts';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

export function auditChatFeatureBarrelGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): ChatFeatureBarrelGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P160',
    module: 'src/features/chat/index.ts',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P160 ChatFeatureBarrel Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
