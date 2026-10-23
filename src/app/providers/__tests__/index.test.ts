import { describe, expect, it } from 'vitest';

import {
  formatProvidersBarrelJson,
  formatProvidersBarrelSummary,
} from '../index';

describe('providers barrel audit helpers', () => {
  it('formats providers barrel summary', () => {
    expect(formatProvidersBarrelSummary()).toBe(
      'exports=AppProviders,ErrorBoundary,QueryClientProvider,ThemeProvider,ToastProvider,useTheme · count=6',
    );
  });

  it('exports providers barrel JSON snapshot', () => {
    const parsed = JSON.parse(formatProvidersBarrelJson());
    expect(parsed.count).toBe(6);
    expect(parsed.exports).toContain('AppProviders');
  });
});

