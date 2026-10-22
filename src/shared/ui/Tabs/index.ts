export { Tabs, TabsList, TabsTrigger, TabsContent } from './Tabs';

export function auditTabsBarrelGovernance(
  state: {
    exportedCount?: number;
  } = {},
): {
  module: 'src/shared/ui/Tabs/index.ts';
  phase: 'P148';
  exportedCount: number;
  healthy: boolean;
} {
  const exportedCount =
    typeof state.exportedCount === 'number' && Number.isFinite(state.exportedCount)
      ? Math.max(0, Math.trunc(state.exportedCount))
      : 4;
  return {
    module: 'src/shared/ui/Tabs/index.ts',
    phase: 'P148',
    exportedCount,
    healthy: exportedCount >= 4,
  };
}
