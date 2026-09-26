/**
 * previewRevision tests — F2 (office-p0-a) cache identity.
 *
 * The regression these pin: the old `${id}:${file_size_bytes}` key could
 * not distinguish two different documents of the same byte size, so the
 * preview could show a stale rendering of a file that had already changed.
 */

import { describe, expect, it } from 'vitest';

import { buildPreviewCacheKey, isCurrentKey, isRevisionConflict } from '../previewRevision';

describe('buildPreviewCacheKey', () => {
  it('separates same-size edits by content revision', () => {
    const before = buildPreviewCacheKey({
      docId: 'doc-1',
      revision: 'sha256:aaa',
      updatedAt: 1,
      sizeBytes: 2048,
    });
    const after = buildPreviewCacheKey({
      docId: 'doc-1',
      revision: 'sha256:bbb',
      updatedAt: 1,
      sizeBytes: 2048,
    });

    expect(before.key).not.toBe(after.key);
    expect(before.degraded).toBe(false);
  });

  it('is stable for the same revision', () => {
    const input = { docId: 'doc-1', revision: 'sha256:aaa', updatedAt: 1, sizeBytes: 10 };
    expect(buildPreviewCacheKey(input).key).toBe(buildPreviewCacheKey(input).key);
  });

  it('separates different documents that share a revision value', () => {
    const a = buildPreviewCacheKey({ docId: 'doc-1', revision: 'sha256:same' });
    const b = buildPreviewCacheKey({ docId: 'doc-2', revision: 'sha256:same' });
    expect(a.key).not.toBe(b.key);
  });

  it('falls back to updated_at/size and flags the degradation', () => {
    const fallback = buildPreviewCacheKey({
      docId: 'doc-1',
      revision: null,
      updatedAt: 1700,
      sizeBytes: 2048,
    });

    expect(fallback.degraded).toBe(true);
    expect(fallback.key).toContain('legacy');
    expect(fallback.key).not.toBe(
      buildPreviewCacheKey({ docId: 'doc-1', updatedAt: 1701, sizeBytes: 2048 }).key,
    );
  });

  it('treats an empty revision string as missing', () => {
    expect(buildPreviewCacheKey({ docId: 'doc-1', revision: '' }).degraded).toBe(true);
  });
});

describe('isCurrentKey', () => {
  it('accepts a response requested for the key still on screen', () => {
    expect(isCurrentKey('doc-1@sha256:a', 'doc-1@sha256:a')).toBe(true);
  });

  it('rejects a late response from a superseded key', () => {
    expect(isCurrentKey('doc-1@sha256:a', 'doc-1@sha256:b')).toBe(false);
  });
});

describe('isRevisionConflict', () => {
  it.each([
    'Request failed with status 409',
    'OfficeRevisionConflictError: document revision mismatch',
    'revision_conflict',
  ])('recognises %s', (message) => {
    expect(isRevisionConflict(message)).toBe(true);
  });

  it('does not swallow unrelated failures', () => {
    expect(isRevisionConflict('op replace_text rejected: text_not_found')).toBe(false);
    expect(isRevisionConflict('Request failed with status 422')).toBe(false);
  });
});
