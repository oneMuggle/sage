import { describe, expect, it } from 'vitest';

import {
  formatQueryClientConfigJson,
  formatQueryClientConfigSummary,
} from '../QueryClientProvider';

describe('QueryClientProvider audit helpers', () => {
  it('formats query client config summary', () => {
    expect(formatQueryClientConfigSummary()).toBe(
      'staleTimeMs=30000 · retry=1 · refetchOnWindowFocus=false',
    );
    expect(formatQueryClientConfigSummary(-10, -2, true)).toBe(
      'staleTimeMs=0 · retry=0 · refetchOnWindowFocus=true',
    );
  });

  it('exports query client config JSON snapshot', () => {
    expect(JSON.parse(formatQueryClientConfigJson(15000, 2, false))).toEqual({
      staleTimeMs: 15000,
      retry: 2,
      refetchOnWindowFocus: false,
    });
  });
});

