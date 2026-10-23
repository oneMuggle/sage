export * from './api';
export function formatArenaEntityBarrelSummary(): string {
  return 'module=entities/arena · base=/api/v1/arena · reExports=api';
}

export function formatArenaEntityBarrelJson(): string {
  return JSON.stringify({
    module: 'entities/arena',
    base: '/api/v1/arena',
    reExports: ['api'],
  });
}

export function auditArenaEntityBarrelGovernance(
  state: {
    exportedHelperCount?: number;
  } = {},
): {
  module: 'src/entities/arena/index.ts';
  phase: 'P152';
  exportedHelperCount: number;
  healthy: boolean;
} {
  const exportedHelperCount =
    typeof state.exportedHelperCount === 'number' && Number.isFinite(state.exportedHelperCount)
      ? Math.max(0, Math.trunc(state.exportedHelperCount))
      : 20;
  return {
    module: 'src/entities/arena/index.ts',
    phase: 'P152',
    exportedHelperCount,
    healthy: exportedHelperCount >= 5,
  };
}
