/**
 * Blob URL helpers for Office preview — factored out of `OfficePreviewPanel`
 * to keep that file under the architecture `maxFileLines` ceiling.
 *
 * The Chromium PDF viewer renders `blob:` URLs reliably but is flaky with
 * `data:` URLs (often blank or forcing a download). These helpers convert
 * a backend `data:application/pdf;base64,…` payload to a blob URL, and
 * revoke the blob URL safely (only if the string actually looks like one).
 */

/**
 * Convert a `data:` URL into a `blob:` URL. Throws on malformed input so
 * callers can downgrade gracefully (e.g. keep the structured preview).
 *
 * The implementation parses the data URL by hand instead of `fetch()`-ing
 * it: jsdom (used by the test suite) and older Chromium builds handle
 * `fetch('data:…')` inconsistently, while the parser works identically in
 * Node / jsdom / the browser.
 */
export async function dataUrlToBlobUrl(dataUrl: string): Promise<string> {
  const match = /^data:([^;,]*)(;base64)?,(.*)$/s.exec(dataUrl);
  if (!match) {
    throw new Error(`invalid data URL: ${dataUrl.slice(0, 60)}`);
  }
  const mime = match[1] || 'application/octet-stream';
  const isBase64 = match[2] === ';base64';
  const payload = match[3];
  const binary = isBase64 ? atob(payload) : decodeURIComponent(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mime });
  return URL.createObjectURL(blob);
}

/** Revoke a blob URL only when the string actually looks like one. */
export function safeRevokeBlobUrl(url: string | null): void {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
