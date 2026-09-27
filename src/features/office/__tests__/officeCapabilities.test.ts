import { describe, expect, it } from 'vitest';

import type { OfficeCapabilities } from '../../../shared/api/types';
import { pdfAvailableForDocument, pdfFormats } from '../officeCapabilities';

const wordOnly: OfficeCapabilities = {
  platform: 'win32',
  soffice_available: false,
  word_com_available: true,
  pdf_export_available: true,
  pillow_available: false,
  formulas_available: false,
  ocr_available: false,
};

describe('format-specific PDF converter discovery', () => {
  it('does not advertise XLSX/PPTX from a legacy Word-only aggregate flag', () => {
    expect(pdfFormats(wordOnly)).toEqual(['docx']);
    expect(pdfAvailableForDocument(wordOnly, 'word')).toBe(true);
    expect(pdfAvailableForDocument(wordOnly, 'excel')).toBe(false);
    expect(pdfAvailableForDocument(wordOnly, 'ppt')).toBe(false);
  });

  it('supports all three formats when LibreOffice is discovered', () => {
    const caps = { ...wordOnly, soffice_available: true };
    expect(pdfFormats(caps)).toEqual(['docx', 'xlsx', 'pptx']);
    expect(pdfAvailableForDocument(caps, 'excel')).toBe(true);
    expect(pdfAvailableForDocument(caps, 'ppt')).toBe(true);
  });

  it('uses explicit new discovery fields rather than contradictory legacy flags', () => {
    expect(pdfFormats({ ...wordOnly, pdf_export_formats: [] })).toEqual([]);
    expect(pdfAvailableForDocument({ ...wordOnly, pdf_export_formats: ['xlsx'] }, 'word')).toBe(false);
    expect(pdfAvailableForDocument({ ...wordOnly, pdf_export_formats: ['xlsx'] }, 'excel')).toBe(true);
  });

  it('fails closed while discovery is unavailable and never converts PDF input', () => {
    expect(pdfAvailableForDocument(null, 'word')).toBe(false);
    expect(pdfAvailableForDocument(wordOnly)).toBe(false);
    expect(pdfAvailableForDocument(wordOnly, 'pdf')).toBe(false);
    expect(pdfFormats({ ...wordOnly, word_com_available: false })).toEqual([]);
  });
});
