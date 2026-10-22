/**
 * Agent Widgets - Agent management UI components
 */
export { AgentCard } from './AgentCard';
export { AgentDetails } from './AgentDetails';
export { EditAgentForm } from './EditAgentForm';

export interface AgentsWidgetBarrelAuditReport {
  schemaVersion: '1.0';
  module: 'src/widgets/agents/index.ts';
  exportedSymbols: readonly string[];
  symbolCount: number;
  exportedAt: string;
}

export function auditAgentsWidgetBarrel(): AgentsWidgetBarrelAuditReport {
  const exportedSymbols = ['AgentCard', 'AgentDetails', 'EditAgentForm'] as const;
  return {
    schemaVersion: '1.0',
    module: 'src/widgets/agents/index.ts',
    exportedSymbols,
    symbolCount: exportedSymbols.length,
    exportedAt: '2026-10-22',
  };
}

export function exportAgentsWidgetBarrelAuditJson(): string {
  return JSON.stringify(auditAgentsWidgetBarrel(), null, 2);
}
