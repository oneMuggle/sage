export { AccountTable } from './AccountTable';
export { BatchRegisterPanel } from './BatchRegisterPanel';
export { DrawPanel } from './DrawPanel';
export { JobConsole } from './JobConsole';
export { ObservationFeed } from './ObservationFeed';
export { RegisterAssist } from './RegisterAssist';
export { TokenWindowCard } from './TokenWindowCard';

export interface ArenaWidgetBarrelAuditReport {
  schemaVersion: '1.0';
  module: 'src/widgets/arena/index.ts';
  exportedSymbols: readonly string[];
  symbolCount: number;
  exportedAt: string;
}

export function auditArenaWidgetBarrel(): ArenaWidgetBarrelAuditReport {
  const exportedSymbols = [
    'AccountTable',
    'BatchRegisterPanel',
    'DrawPanel',
    'JobConsole',
    'ObservationFeed',
    'RegisterAssist',
    'TokenWindowCard',
  ] as const;
  return {
    schemaVersion: '1.0',
    module: 'src/widgets/arena/index.ts',
    exportedSymbols,
    symbolCount: exportedSymbols.length,
    exportedAt: '2026-10-22',
  };
}

export function exportArenaWidgetBarrelAuditJson(): string {
  return JSON.stringify(auditArenaWidgetBarrel(), null, 2);
}
export function auditArenaIndexGovernance(): string {
  return JSON.stringify({
    module: 'arena-index',
    phase: 'P185',
    audited: true,
  });
}
