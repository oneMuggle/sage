export { Chat } from './Chat';
export { Settings } from './settings';
export { Memory } from './Memory';
export { Welcome } from './Welcome';
export { default as Arena } from './Arena';

export function auditPagesBarrelGovernance(
  state: {
    exportedPageCount?: number;
    lazyRoutesEnabled?: boolean;
  } = {},
): {
  module: 'src/pages/index.ts';
  phase: 'P142';
  exportedPageCount: number;
  lazyRoutesEnabled: boolean;
  healthy: boolean;
} {
  const exportedPageCount =
    typeof state.exportedPageCount === 'number' && Number.isFinite(state.exportedPageCount)
      ? Math.max(0, Math.trunc(state.exportedPageCount))
      : 5;
  const lazyRoutesEnabled = state.lazyRoutesEnabled !== false;
  return {
    module: 'src/pages/index.ts',
    phase: 'P142',
    exportedPageCount,
    lazyRoutesEnabled,
    healthy: exportedPageCount > 0 && lazyRoutesEnabled,
  };
}
