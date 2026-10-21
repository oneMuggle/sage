import { describe, expect, it } from 'vitest';

import {
  formatRuntimeDiagnosisSummary,
  formatRuntimeDiagnosisJson,
} from '../runtimeTypes';

describe('runtimeTypes audit helpers', () => {
  it('formats project runtime diagnosis summary and json', () => {
    const diag = {
      level: 'satisfied' as const,
      diagnostics: [],
      manifests: [{ language: 'python', path: 'pyproject.toml', kind: 'pyproject', requires: [], extras: {} }],
      recommended_runtime: '/usr/bin/python3',
      probe_errors: [],
    };
    expect(formatRuntimeDiagnosisSummary(diag)).toBe(
      'level=satisfied · findings=0 · manifests=1 · runtime=/usr/bin/python3',
    );
    const parsed = JSON.parse(formatRuntimeDiagnosisJson(diag));
    expect(parsed).toEqual({
      level: 'satisfied',
      findingCount: 0,
      manifestCount: 1,
      recommendedRuntime: '/usr/bin/python3',
      probeErrorCount: 0,
    });
  });

  it('handles nullish diagnosis safely', () => {
    expect(formatRuntimeDiagnosisSummary(null)).toBe(
      'level=unsatisfied · findings=0 · manifests=0 · runtime=none',
    );
    expect(JSON.parse(formatRuntimeDiagnosisJson(undefined)).recommendedRuntime).toBeNull();
  });
});
