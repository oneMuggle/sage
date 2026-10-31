import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { parseHttpRange, resolvePetPackUrl } from '../pet/packProtocol';

let root: string;
let packsDir: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'pet-proto-'));
  packsDir = join(root, 'pets');
  mkdirSync(join(packsDir, 'my-pet', 'frames'), { recursive: true });
  writeFileSync(join(packsDir, 'my-pet', 'idle.webm'), Buffer.from([1, 2, 3, 4]));
  writeFileSync(join(packsDir, 'my-pet', 'frames', '待机.webm'), Buffer.from([5, 6]));
  writeFileSync(join(root, 'secret.webm'), Buffer.from([9, 9, 9]));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe('resolvePetPackUrl', () => {
  it('resolves files inside the pack directory', () => {
    const result = resolvePetPackUrl('sage-pet://my-pet/idle.webm', packsDir);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.mime).toBe('video/webm');
      expect(result.size).toBe(4);
    }
  });

  it('decodes percent-encoded Chinese file names', () => {
    const result = resolvePetPackUrl(
      'sage-pet://my-pet/frames/%E5%BE%85%E6%9C%BA.webm',
      packsDir,
    );
    expect(result.ok).toBe(true);
  });

  it('rejects path traversal, including encoded segments', () => {
    expect(resolvePetPackUrl('sage-pet://my-pet/../secret.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://my-pet/%2e%2e/secret.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://my-pet/..%2Fsecret.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://my-pet/%2Fetc%2Fpasswd', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://my-pet/a%5Cb.webm', packsDir).ok).toBe(false);
  });

  it('rejects ids that could escape the packs directory', () => {
    expect(resolvePetPackUrl('sage-pet://..%2Fpets/a.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://a/b.webm', packsDir).ok).toBe(false);
  });

  it('serves only whitelisted asset extensions', () => {
    expect(resolvePetPackUrl('sage-pet://my-pet/pack.json', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://my-pet/missing.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('sage-pet://other/idle.webm', packsDir).ok).toBe(false);
  });

  it('rejects other schemes', () => {
    expect(resolvePetPackUrl('file:///tmp/x.webm', packsDir).ok).toBe(false);
    expect(resolvePetPackUrl('not a url', packsDir).ok).toBe(false);
  });
});

describe('parseHttpRange', () => {
  it('returns none without a Range header', () => {
    expect(parseHttpRange(undefined, 10)).toEqual({ kind: 'none' });
  });

  it('parses closed, open and suffix ranges', () => {
    expect(parseHttpRange('bytes=0-3', 10)).toEqual({ kind: 'range', start: 0, end: 3 });
    expect(parseHttpRange('bytes=5-', 10)).toEqual({ kind: 'range', start: 5, end: 9 });
    expect(parseHttpRange('bytes=-3', 10)).toEqual({ kind: 'range', start: 7, end: 9 });
    expect(parseHttpRange('bytes=8-20', 10)).toEqual({ kind: 'range', start: 8, end: 9 });
  });

  it('rejects malformed or unsatisfiable ranges', () => {
    expect(parseHttpRange('bytes=10-', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('bytes=5-3', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('bytes=-', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('bytes=-0', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('bytes=abc', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('bytes=0-1,3-4', 10)).toEqual({ kind: 'invalid' });
    expect(parseHttpRange('items=0-1', 10)).toEqual({ kind: 'invalid' });
  });
});
