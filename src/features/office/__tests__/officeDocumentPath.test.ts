import { describe, expect, it } from 'vitest';

import { officeDocumentPath } from '../officeDocumentPath';

describe('officeDocumentPath', () => {
  it('mirrors the backend <workspace>/office/<doc_type>/<id>/<filename> layout', () => {
    expect(
      officeDocumentPath({
        workspace_path: '/ws',
        doc_type: 'word',
        id: 'abc123',
        generated_filename: 'report.docx',
      }),
    ).toBe('/ws/office/word/abc123/report.docx');
  });

  it('returns null when the summary has no workspace_path', () => {
    expect(
      officeDocumentPath({
        doc_type: 'word',
        id: 'abc123',
        generated_filename: 'report.docx',
      }),
    ).toBeNull();
  });

  it('does not double the separator when the workspace ends with one', () => {
    expect(
      officeDocumentPath({
        workspace_path: '/ws/',
        doc_type: 'ppt',
        id: 'd2',
        generated_filename: 'deck.pptx',
      }),
    ).toBe('/ws/office/ppt/d2/deck.pptx');
  });
});
