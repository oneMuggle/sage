import { describe, expect, it } from 'vitest';

import {
  formatToastProviderJson,
  formatToastProviderSummary,
} from '../ToastProvider';

describe('ToastProvider audit helpers', () => {
  it('formats toast provider summary', () => {
    expect(formatToastProviderSummary('dark', 4000)).toBe(
      'theme=dark · position=top-right · durationMs=4000',
    );
    expect(formatToastProviderSummary('light', -5)).toBe(
      'theme=light · position=top-right · durationMs=0',
    );
  });

  it('exports toast provider JSON snapshot', () => {
    expect(JSON.parse(formatToastProviderJson('dark', 3500))).toEqual({
      theme: 'dark',
      position: 'top-right',
      richColors: true,
      closeButton: true,
      durationMs: 3500,
    });
  });
});

