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
 * Decode a `data:` URL into a `Blob`. Throws on malformed input so callers
 * can downgrade gracefully (e.g. keep the structured preview).
 *
 * Parses the data URL by hand instead of `fetch()`-ing it: the packaged
 * build injects a CSP whose `connect-src` deliberately omits `data:` (see
 * `cspInjectionPlugin` in vite.config.ts), so `fetch('data:…')` is blocked
 * in production while working in dev (no CSP). jsdom / older Chromium also
 * handle `fetch('data:…')` inconsistently; the parser works identically in
 * Node / jsdom / the browser.
 */
export function dataUrlToBlob(dataUrl: string): Blob {
  const match = /^data:([^;,]*)(;base64)?,(.*)$/s.exec(dataUrl);
  if (!match) {
    throw new Error(`invalid data URL: ${dataUrl.slice(0, 60)}`);
  }
  const mime = match[1] || 'application/octet-stream';
  const bytes =
    match[2] === ';base64'
      ? Uint8Array.from(atob(match[3]), (c) => c.charCodeAt(0))
      : new TextEncoder().encode(decodeURIComponent(match[3]));
  return new Blob([bytes], { type: mime });
}

/**
 * Convert a `data:` URL into a `blob:` URL. Throws on malformed input so
 * callers can downgrade gracefully (e.g. keep the structured preview).
 */
export async function dataUrlToBlobUrl(dataUrl: string): Promise<string> {
  return URL.createObjectURL(dataUrlToBlob(dataUrl));
}

/** Revoke a blob URL only when the string actually looks like one. */
export function safeRevokeBlobUrl(url: string | null): void {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
