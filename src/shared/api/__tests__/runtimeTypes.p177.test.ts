import { describe, expect, it } from 'vitest';

import {
  auditRuntimeTypesGovernance,
  formatRuntimeDiagnosisJson,
  formatRuntimeDiagnosisSummary,
} from '../runtimeTypes';

describe('runtimeTypes P177 governance audit', () => {
  it('audits runtimeTypes governance contract and diagnosis formatters', () => {
    const raw = auditRuntimeTypesGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.runtime_types.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.diagnosisLevels).toEqual(['satisfied', 'degraded', 'unsatisfied']);
    expect(formatRuntimeDiagnosisSummary(null)).toContain('level=unsatisfied');
    expect(JSON.parse(formatRuntimeDiagnosisJson({ level: 'satisfied' })).level).toBe('satisfied');
  });
});
