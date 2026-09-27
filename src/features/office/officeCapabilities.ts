import type { OfficeCapabilities, OfficeDocType } from '../../shared/api/types';

type PdfSourceFormat = 'docx' | 'xlsx' | 'pptx';

/** Discovery is format-specific, never a promise of successful conversion. */
export function pdfFormats(caps: OfficeCapabilities | null): PdfSourceFormat[] {
  if (!caps) return [];
  if (caps.pdf_export_formats !== undefined) return caps.pdf_export_formats;
  // Legacy aggregate pdf_export_available incorrectly included XLSX/PPTX for Word.
  if (caps.soffice_available) return ['docx', 'xlsx', 'pptx'];
  return caps.word_com_available ? ['docx'] : [];
}

export function pdfAvailableForDocument(
  caps: OfficeCapabilities | null,
  docType?: OfficeDocType,
): boolean {
  const format = docType === 'word' ? 'docx' : docType === 'excel' ? 'xlsx' : docType === 'ppt' ? 'pptx' : null;
  return format !== null && pdfFormats(caps).includes(format);
}
