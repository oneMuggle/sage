import { describe, expect, it } from 'vitest';

import {
  auditUseOfficeDocumentsGovernance,
  formatOfficeDocumentsBatchJson,
  formatOfficeDocumentsBatchSummary,
} from '../useOfficeDocuments';

describe('useOfficeDocuments governance audit (P165)', () => {
  it('returns ready governance status for useOfficeDocuments', () => {
    const snap = auditUseOfficeDocumentsGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/useOfficeDocuments.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('formats office documents batch summary and json', () => {
    const res = { succeeded: ['a', 'b'], failed: ['c'] };
    expect(formatOfficeDocumentsBatchSummary(res)).toBe('succeeded=2 · failed=1');
    expect(JSON.parse(formatOfficeDocumentsBatchJson(res))).toMatchObject({
      total: 3,
      succeededCount: 2,
      failedCount: 1,
    });
  });
});
