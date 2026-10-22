export { DiagnosticCard } from './DiagnosticCard';
export { ExportButton } from './ExportButton';
export { useDiagnosticPreview } from './useDiagnosticPreview';
export type { PreviewResponse } from './useDiagnosticPreview';
export { BrowserEnvironmentSection } from './BrowserEnvironmentSection';
export function formatDiagnosticFeatureBarrelSummary(): string {
  return 'module=features/diagnostic · exports=DiagnosticCard,ExportButton,useDiagnosticPreview · count=3';
}

export function formatDiagnosticFeatureBarrelJson(): string {
  return JSON.stringify({
    module: 'features/diagnostic',
    exports: ['DiagnosticCard', 'ExportButton', 'useDiagnosticPreview'],
    count: 3,
  });
}

export interface DiagnosticBarrelGovernanceAudit {
  phase: 'P162';
  module: 'src/features/diagnostic/index.ts';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

export function auditDiagnosticBarrelGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): DiagnosticBarrelGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P162',
    module: 'src/features/diagnostic/index.ts',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P162 DiagnosticBarrel Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
