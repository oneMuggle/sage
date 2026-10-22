import { describe, expect, it } from 'vitest';

import { auditOfficeStructuredPreviewsGovernance } from '../OfficeStructuredPreviews';

describe('OfficeStructuredPreviews P142 governance audit', () => {
  it('returns healthy defaults for office structured previews', () => {
    const res = auditOfficeStructuredPreviewsGovernance();
    expect(res.module).toBe('src/features/office/OfficeStructuredPreviews.tsx');
    expect(res.phase).toBe('P142');
    expect(res.previewKind).toBe('ppt');
    expect(res.slideCount).toBe(5);
    expect(res.sectionCount).toBe(4);
    expect(res.sheetCount).toBe(2);
    expect(res.healthy).toBe(true);
  });

  it('normalizes previewKind and item counts', () => {
    const res = auditOfficeStructuredPreviewsGovernance({
      previewKind: 'xlsx',
      slideCount: -1,
      sectionCount: 6.8,
      sheetCount: 3.2,
    });
    expect(res.previewKind).toBe('xlsx');
    expect(res.slideCount).toBe(0);
    expect(res.sectionCount).toBe(6);
    expect(res.sheetCount).toBe(3);
    expect(res.healthy).toBe(true);
  });
});
