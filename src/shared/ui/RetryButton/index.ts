export { RetryButton } from './RetryButton';
export type { RetryButtonProps } from './RetryButton';

export function auditRetryButtonBarrelGovernance(
  state: {
    cooldownSeconds?: number;
  } = {},
): {
  module: 'src/shared/ui/RetryButton/index.ts';
  phase: 'P148';
  cooldownSeconds: number;
  healthy: boolean;
} {
  const cooldownSeconds =
    typeof state.cooldownSeconds === 'number' && Number.isFinite(state.cooldownSeconds)
      ? Math.max(0, Math.min(300, Math.trunc(state.cooldownSeconds)))
      : 0;
  return {
    module: 'src/shared/ui/RetryButton/index.ts',
    phase: 'P148',
    cooldownSeconds,
    healthy: cooldownSeconds >= 0 && cooldownSeconds <= 300,
  };
}
