import { describe, expect, it } from 'vitest';

import {
  auditDocxNativePreviewGovernance,
  formatDocxPreviewMetaJson,
  formatDocxPreviewMetaMarkdown,
} from '../DocxNativePreview';

describe('DocxNativePreview governance audit (P164)', () => {
  it('returns ready governance status for DocxNativePreview', () => {
    const snap = auditDocxNativePreviewGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/DocxNativePreview.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats docx preview meta markdown and json', () => {
    const params = {
      workspacePath: '/ws',
      managedPath: '/ws/doc.docx',
      revision: 'r1',
      state: 'ok' as const,
    };
    expect(formatDocxPreviewMetaMarkdown(params)).toContain('/ws/doc.docx');
    expect(JSON.parse(formatDocxPreviewMetaJson(params))).toMatchObject({
      workspacePath: '/ws',
      managedPath: '/ws/doc.docx',
      revision: 'r1',
      state: 'ok',
    });
  });
});
