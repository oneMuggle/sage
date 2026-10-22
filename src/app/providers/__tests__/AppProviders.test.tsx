import { describe, expect, it } from 'vitest';

import {
  formatAppProvidersJson,
  formatAppProvidersSummary,
} from '../AppProviders';

describe('AppProviders audit helpers', () => {
  it('formats app providers stack summary', () => {
    expect(formatAppProvidersSummary(true)).toBe(
      'stack=ErrorBoundary>Theme>Font>SessionWorkspace>I18n>QueryClient · toast=sibling · children=true',
    );
    expect(formatAppProvidersSummary(false)).toContain('children=false');
  });

  it('exports app providers JSON snapshot', () => {
    const parsed = JSON.parse(formatAppProvidersJson(true));
    expect(parsed.toastPlacement).toBe('sibling');
    expect(parsed.hasChildren).toBe(true);
    expect(parsed.stack).toContain('QueryClientProvider');
  });
});

