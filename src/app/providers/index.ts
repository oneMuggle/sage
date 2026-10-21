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

