import { describe, expect, it } from 'vitest';

import {
  formatDiagnosticFeatureBarrelJson,
  formatDiagnosticFeatureBarrelSummary,
} from '../index';

describe('diagnostic feature barrel audit helpers', () => {
  it('formats diagnostic feature barrel summary', () => {
    expect(formatDiagnosticFeatureBarrelSummary()).toBe(
      'module=features/diagnostic · exports=DiagnosticCard,ExportButton,useDiagnosticPreview · count=3',
    );
  });

  it('exports diagnostic feature barrel JSON snapshot', () => {
    const parsed = JSON.parse(formatDiagnosticFeatureBarrelJson());
    expect(parsed.count).toBe(3);
    expect(parsed.exports).toContain('DiagnosticCard');
  });
});

