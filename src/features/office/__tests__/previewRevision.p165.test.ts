import { describe, expect, it } from 'vitest';

import {
  auditPreviewRevisionGovernance,
  buildPreviewCacheKey,
  formatPreviewRevisionJson,
  formatPreviewRevisionSummary,
} from '../previewRevision';

describe('previewRevision governance audit (P165)', () => {
  it('returns ready governance status for previewRevision', () => {
    const snap = auditPreviewRevisionGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/previewRevision.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('builds and formats preview revision cache key', () => {
    const key = buildPreviewCacheKey({ docId: 'doc-1', revision: 'sha256:abc' });
    expect(formatPreviewRevisionSummary(key)).toContain('doc-1@sha256:abc · verified');
    expect(JSON.parse(formatPreviewRevisionJson(key))).toEqual({
      key: 'doc-1@sha256:abc',
      degraded: false,
      hasKey: true,
    });
  });
});
