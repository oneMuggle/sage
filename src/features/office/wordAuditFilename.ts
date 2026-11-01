/** Derive the default fixed output filename for the Word audit panel (M2c). */
export function defaultFixedName(filename: string | undefined, filePath: string): string {
  const raw = (filename || filePath.split('/').pop() || 'document.docx').trim();
  if (!raw.toLowerCase().endsWith('.docx')) return 'document-fixed.docx';
  return `${raw.slice(0, -'.docx'.length)}-fixed.docx`;
}
