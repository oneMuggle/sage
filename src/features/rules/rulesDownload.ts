/** Download a text payload as a file in the renderer (rules center, 2026-11-08). */
export function downloadRulesText(filename: string, text: string, mime: string): void {
  if (typeof URL.createObjectURL !== 'function') return;
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
