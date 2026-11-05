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
 * Convert a `data:` URL into a `blob:` URL. Throws on network failure so
 * callers can downgrade gracefully (e.g. keep the structured preview).
 */
export async function dataUrlToBlobUrl(dataUrl: string): Promise<string> {
  const res = await fetch(dataUrl);
  if (!res.ok) throw new Error(`data URL fetch failed: ${res.status}`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/** Revoke a blob URL only when the string actually looks like one. */
export function safeRevokeBlobUrl(url: string | null): void {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
