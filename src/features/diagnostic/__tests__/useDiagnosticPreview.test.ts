import { describe, expect, it } from 'vitest';

import {
  formatDiagnosticPreviewJson,
  formatDiagnosticPreviewSummary,
} from '../useDiagnosticPreview';

describe('useDiagnosticPreview audit helpers', () => {
  it('formats diagnostic preview summary', () => {
    expect(
      formatDiagnosticPreviewSummary(
        { count: 14, version: '1.2.0', sampleUrls: ['https://a.test'] },
        false,
        false,
      ),
    ).toBe('count=14 · version=1.2.0 · loading=false · error=false');
  });

  it('serializes diagnostic preview audit JSON', () => {
    expect(
      JSON.parse(
        formatDiagnosticPreviewJson(
          { count: 3, version: '2.0.0', sampleUrls: ['a', 'b'] },
          true,
          false,
        ),
      ),
    ).toEqual({
      count: 3,
      version: '2.0.0',
      sampleCount: 2,
      loading: true,
      hasError: false,
    });
  });
});
