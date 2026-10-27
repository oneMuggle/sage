export { ErrorState } from './ErrorState';

export function auditErrorStateBarrelGovernance(
  state: {
    hasRetryCallback?: boolean;
  } = {},
): {
  module: 'src/shared/ui/ErrorState/index.ts';
  phase: 'P147';
  hasRetryCallback: boolean;
  healthy: boolean;
} {
  const hasRetryCallback = state.hasRetryCallback !== false;
  return {
    module: 'src/shared/ui/ErrorState/index.ts',
    phase: 'P147',
    hasRetryCallback,
    healthy: hasRetryCallback,
  };
}
