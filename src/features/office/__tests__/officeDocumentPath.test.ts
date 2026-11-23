import { describe, expect, it } from 'vitest';

import { officeDocumentPath, officeDocumentRelativePath } from '../officeDocumentPath';

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

describe('officeDocumentRelativePath', () => {
  it('builds the workspace-relative form used by the right-panel preview', () => {
    expect(
      officeDocumentRelativePath({
        doc_type: 'word',
        id: 'abc123',
        generated_filename: 'report.docx',
      }),
    ).toBe('office/word/abc123/report.docx');
  });

  it('keeps the same layout for other document types', () => {
    expect(
      officeDocumentRelativePath({
        doc_type: 'excel',
        id: 'd3',
        generated_filename: 'book.xlsx',
      }),
    ).toBe('office/excel/d3/book.xlsx');
  });
});
