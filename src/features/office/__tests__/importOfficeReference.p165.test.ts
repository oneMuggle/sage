import { describe, expect, it } from 'vitest';

import {
  auditImportOfficeReferenceGovernance,
  formatOfficeImportRefJson,
  formatOfficeImportRefSummary,
} from '../importOfficeReference';

describe('importOfficeReference governance audit (P165)', () => {
  it('returns ready governance status for importOfficeReference', () => {
    const snap = auditImportOfficeReferenceGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/importOfficeReference.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('formats office import reference summary and json', () => {
    const ref = { docId: 'd1', docType: 'word' as const, filename: 'report.docx' };
    expect(formatOfficeImportRefSummary(ref)).toBe('d1 · word · report.docx');
    expect(JSON.parse(formatOfficeImportRefJson(ref))).toEqual(ref);
  });
});
