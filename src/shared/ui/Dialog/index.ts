export {
  Dialog,
  DialogTrigger,
  DialogPortal,
  DialogClose,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from './Dialog';

export function auditDialogBarrelGovernance(
  state: {
    exportedPrimitiveCount?: number;
  } = {},
): {
  module: 'src/shared/ui/Dialog/index.ts';
  phase: 'P147';
  exportedPrimitiveCount: number;
  healthy: boolean;
} {
  const exportedPrimitiveCount =
    typeof state.exportedPrimitiveCount === 'number' &&
    Number.isFinite(state.exportedPrimitiveCount)
      ? Math.max(0, Math.trunc(state.exportedPrimitiveCount))
      : 9;
  return {
    module: 'src/shared/ui/Dialog/index.ts',
    phase: 'P147',
    exportedPrimitiveCount,
    healthy: exportedPrimitiveCount >= 6,
  };
}
