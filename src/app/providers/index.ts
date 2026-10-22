export { AppProviders } from './AppProviders';
export { ErrorBoundary } from './ErrorBoundary';
export { QueryClientProvider } from './QueryClientProvider';
export { ThemeProvider } from './ThemeProvider';
export { ToastProvider } from './ToastProvider';
export { useTheme, type ThemeMode } from './useTheme';
export function formatProvidersBarrelSummary(): string {
  return 'exports=AppProviders,ErrorBoundary,QueryClientProvider,ThemeProvider,ToastProvider,useTheme · count=6';
}

export function formatProvidersBarrelJson(): string {
  return JSON.stringify({
    exports: [
      'AppProviders',
      'ErrorBoundary',
      'QueryClientProvider',
      'ThemeProvider',
      'ToastProvider',
      'useTheme',
    ],
    count: 6,
  });
}

export function auditProvidersBarrelGovernance(
  state: {
    exportedCount?: number;
  } = {},
): {
  module: 'src/app/providers/index.ts';
  phase: 'P151';
  exportedCount: number;
  healthy: boolean;
} {
  const exportedCount =
    typeof state.exportedCount === 'number' && Number.isFinite(state.exportedCount)
      ? Math.max(0, Math.trunc(state.exportedCount))
      : 6;
  return {
    module: 'src/app/providers/index.ts',
    phase: 'P151',
    exportedCount,
    healthy: exportedCount >= 5,
  };
}
