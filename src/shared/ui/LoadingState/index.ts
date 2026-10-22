export { LoadingState } from './LoadingState';
export type { LoadingStateProps, LoadingVariant } from './LoadingState';

export function auditLoadingStateBarrelGovernance(
  state: {
    hasAccessibleLabel?: boolean;
  } = {},
): {
  module: 'src/shared/ui/LoadingState/index.ts';
  phase: 'P147';
  hasAccessibleLabel: boolean;
  healthy: boolean;
} {
  const hasAccessibleLabel = state.hasAccessibleLabel !== false;
  return {
    module: 'src/shared/ui/LoadingState/index.ts',
    phase: 'P147',
    hasAccessibleLabel,
    healthy: hasAccessibleLabel,
  };
}
