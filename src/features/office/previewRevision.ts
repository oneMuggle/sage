/**
 * previewRevision — F2 (office-p0-a): cache identity for office previews.
 *
 * The old key was `${doc.id}:${metadata.file_size_bytes}`: any edit that
 * keeps the byte size (a same-length cell value, a swapped word) reused the
 * previous render, so "what the user sees" could differ from "what will be
 * delivered". Keying on the content revision closes that hole.
 *
 * When the backend cannot supply a revision (older build, unreadable file)
 * we fall back to the legacy triple and SAY SO via `degraded`, so callers
 * can decide to re-fetch rather than silently trusting a weak key.
 */

export interface PreviewCacheKeyInput {
  docId: string;
  /** Content revision from GET /office/doc/{id}/revision (sha256:…). */
  revision?: string | null;
  updatedAt?: number | null;
  sizeBytes?: number | null;
}

export interface PreviewCacheKey {
  key: string;
  /** True when the key is the legacy size/mtime fallback, not a content hash. */
  degraded: boolean;
}

export function buildPreviewCacheKey(input: PreviewCacheKeyInput): PreviewCacheKey {
  const { docId, revision, updatedAt, sizeBytes } = input;
  if (typeof revision === 'string' && revision.length > 0) {
    return { key: `${docId}@${revision}`, degraded: false };
  }
  return {
    key: `${docId}@legacy:${updatedAt ?? 0}:${sizeBytes ?? 0}`,
    degraded: true,
  };
}

/**
 * Guard for late async responses: a render/convert result may land after
 * the user switched documents or the file changed again. Only accept it
 * when the key it was requested for is still the current one.
 */
export function isCurrentKey(requestedKey: string, currentKey: string): boolean {
  return requestedKey === currentKey;
}

/**
 * Recognise the backend's 409 stale-write answer from a thrown API error.
 *
 * The IPC layer flattens HTTP errors to a message string, so this matches
 * the stable parts of that contract: the 409 status, the backend error type
 * and the message text from OfficeRevisionConflictError.
 */
export function isRevisionConflict(message: string): boolean {
  const text = message.toLowerCase();
  return (
    text.includes('409') ||
    text.includes('revision_conflict') ||
    text.includes('revisionconflict') ||
    text.includes('revision mismatch')
  );
}
