/**
 * sage-pet:// protocol — serves user pack assets to the pet renderer.
 *
 * User packs live under `<userData>/pets/<id>/`, outside the app bundle, so
 * the renderer cannot reach them through relative URLs. A dedicated custom
 * scheme keeps file access narrow: only the id shape and asset extensions
 * accepted by packManifest.ts are served, and only from the packs directory.
 *
 * registerStreamProtocol (not registerFileProtocol) is used because Chromium's
 * media stack issues Range requests for WebM playback; the handler answers
 * 206/416 itself so seeking and looping behave like a normal file:// video.
 */
import { createReadStream, statSync } from 'node:fs';
import { extname, join, sep } from 'node:path';
import { Readable } from 'node:stream';

import { logger } from '../logger';
import { isValidPackIdShape } from './packManifest';

export const PET_PACK_SCHEME = 'sage-pet';

const MIME_BY_EXTENSION: Record<string, string> = {
  '.webm': 'video/webm',
  '.mp4': 'video/mp4',
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.apng': 'image/apng',
};

export interface ResolvedPackFile {
  ok: true;
  path: string;
  size: number;
  mime: string;
}

export interface RejectedPackFile {
  ok: false;
  reason: string;
}

/**
 * Resolve `sage-pet://<id>/<relative path>` to a file inside `<packsDir>/<id>`.
 * Each path segment is decoded separately so an encoded `%2F` cannot smuggle
 * a directory separator past the `..` check.
 */
export function resolvePetPackUrl(url: string, packsDir: string): ResolvedPackFile | RejectedPackFile {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, reason: 'invalid url' };
  }
  if (parsed.protocol !== `${PET_PACK_SCHEME}:`) return { ok: false, reason: 'wrong scheme' };
  const id = parsed.hostname;
  if (!isValidPackIdShape(id)) return { ok: false, reason: 'invalid pack id' };

  const rawSegments = parsed.pathname.split('/');
  if (rawSegments.length < 2 || rawSegments[0] !== '') return { ok: false, reason: 'invalid path' };
  const segments: string[] = [];
  for (const raw of rawSegments.slice(1)) {
    if (!raw) return { ok: false, reason: 'empty segment' };
    let decoded: string;
    try {
      decoded = decodeURIComponent(raw);
    } catch {
      return { ok: false, reason: 'bad encoding' };
    }
    if (
      !decoded ||
      decoded === '.' ||
      decoded === '..' ||
      decoded.includes('/') ||
      decoded.includes('\\') ||
      decoded.includes('\0')
    ) {
      return { ok: false, reason: 'unsafe segment' };
    }
    segments.push(decoded);
  }

  const mime = MIME_BY_EXTENSION[extname(segments[segments.length - 1]!).toLowerCase()];
  if (!mime) return { ok: false, reason: 'extension not served' };

  const packDir = join(packsDir, id);
  const path = join(packDir, ...segments);
  if (!path.startsWith(packDir + sep)) return { ok: false, reason: 'path escape' };
  try {
    const stat = statSync(path);
    if (!stat.isFile()) return { ok: false, reason: 'not a file' };
    return { ok: true, path, size: stat.size, mime };
  } catch {
    return { ok: false, reason: 'missing file' };
  }
}

export type HttpRange =
  | { kind: 'none' }
  | { kind: 'invalid' }
  | { kind: 'range'; start: number; end: number };

/** Parse a single-range `Range: bytes=...` header against a file size. */
export function parseHttpRange(header: string | undefined | null, size: number): HttpRange {
  if (!header) return { kind: 'none' };
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return { kind: 'invalid' };
  const [, rawStart, rawEnd] = match;
  if (!rawStart && !rawEnd) return { kind: 'invalid' };
  if (!rawStart) {
    const suffix = Number(rawEnd);
    if (!Number.isInteger(suffix) || suffix <= 0) return { kind: 'invalid' };
    return { kind: 'range', start: Math.max(0, size - suffix), end: size - 1 };
  }
  const start = Number(rawStart);
  const end = rawEnd ? Number(rawEnd) : size - 1;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start > end || start >= size) {
    return { kind: 'invalid' };
  }
  return { kind: 'range', start, end: Math.min(end, size - 1) };
}

let schemeRegistered = false;

/** Must run before `app.whenReady()` resolves. Idempotent. */
export function registerPetPackScheme(): void {
  if (schemeRegistered) return;
  schemeRegistered = true;
  // Electron requires this before the app `ready` event; callers invoke it at
  // module load time from main.ts, so the dynamic import resolves long before.
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerSchemesAsPrivileged([
      {
        scheme: PET_PACK_SCHEME,
        privileges: {
          standard: true,
          secure: true,
          supportFetchAPI: true,
          corsEnabled: true,
          stream: true,
        },
      },
    ]);
  })().catch((error: unknown) => {
    logger.warn('pet: register scheme failed', { error: String(error) });
  });
}

let protocolRegistered = false;

/** Must run after `app.whenReady()`, before the pet window loads. */
export function registerPetPackProtocol(packsDir: string): void {
  if (protocolRegistered) return;
  protocolRegistered = true;
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerStreamProtocol(PET_PACK_SCHEME, (request, callback) => {
      const method = (request.method || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD') {
        callback({ statusCode: 405, headers: { Allow: 'GET, HEAD' }, data: Readable.from([]) });
        return;
      }
      const resolved = resolvePetPackUrl(request.url, packsDir);
      if (!resolved.ok) {
        logger.warn('pet: rejected pack url', { url: request.url, reason: resolved.reason });
        callback({ error: -10 }); // net::ERR_ACCESS_DENIED
        return;
      }
      const rangeHeader = request.headers.range ?? request.headers.Range;
      const range = parseHttpRange(rangeHeader, resolved.size);
      const baseHeaders: Record<string, string> = {
        'Accept-Ranges': 'bytes',
        'Content-Type': resolved.mime,
        'Cache-Control': 'no-cache',
      };
      if (range.kind === 'invalid') {
        callback({
          statusCode: 416,
          headers: { ...baseHeaders, 'Content-Range': `bytes */${resolved.size}` },
          data: Readable.from([]),
        });
        return;
      }
      if (range.kind === 'range') {
        const length = range.end - range.start + 1;
        callback({
          statusCode: 206,
          headers: {
            ...baseHeaders,
            'Content-Length': String(length),
            'Content-Range': `bytes ${range.start}-${range.end}/${resolved.size}`,
          },
          data:
            method === 'HEAD'
              ? Readable.from([])
              : createReadStream(resolved.path, { start: range.start, end: range.end }),
        });
        return;
      }
      callback({
        statusCode: 200,
        headers: { ...baseHeaders, 'Content-Length': String(resolved.size) },
        data: method === 'HEAD' ? Readable.from([]) : createReadStream(resolved.path),
      });
    });
  })().catch((error: unknown) => {
    logger.warn('pet: register pack protocol failed', { error: String(error) });
  });
}
