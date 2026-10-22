export { DiagnosticCard } from './DiagnosticCard';
export { ExportButton } from './ExportButton';
export { useDiagnosticPreview } from './useDiagnosticPreview';
export type { PreviewResponse } from './useDiagnosticPreview';
export { BrowserEnvironmentSection } from './BrowserEnvironmentSection';
export function formatDiagnosticFeatureBarrelSummary(): string {
  return 'module=features/diagnostic · exports=DiagnosticCard,ExportButton,useDiagnosticPreview · count=3';
}

export function formatDiagnosticFeatureBarrelJson(): string {
  return JSON.stringify({
    module: 'features/diagnostic',
    exports: ['DiagnosticCard', 'ExportButton', 'useDiagnosticPreview'],
    count: 3,
  });
}

