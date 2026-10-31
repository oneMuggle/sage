import { describe, expect, it } from 'vitest';

import {
  findPackRoot,
  parsePetPackManifest,
  validatePackEntries,
} from '../pet/packManifest';

const BASE = {
  id: 'my-pet',
  name: '小叶灵',
  version: '1.0.0',
  license: 'CC-BY-4.0',
  canvas: { width: 256, height: 256 },
  anchor: { x: 128, y: 236 },
  actions: {
    idle: ['frames/idle-0.webp'],
    thinking: ['frames/think.webm'],
  },
};

describe('parsePetPackManifest', () => {
  it('accepts a minimal valid manifest and trims text fields', () => {
    const result = parsePetPackManifest({ ...BASE, name: '  小叶灵  ' });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.name).toBe('小叶灵');
      expect(result.value.actions.idle).toEqual(['frames/idle-0.webp']);
    }
  });

  it('drops an empty source and keeps an http(s) source', () => {
    const empty = parsePetPackManifest({ ...BASE, source: '' });
    expect(empty.ok && 'source' in empty.value).toBe(false);
    const withSource = parsePetPackManifest({ ...BASE, source: 'https://example.com/pack' });
    expect(withSource.ok && withSource.value.source).toBe('https://example.com/pack');
  });

  it('rejects reserved and malformed ids', () => {
    expect(parsePetPackManifest({ ...BASE, id: 'dafeiyu' }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, id: 'My Pet' }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, id: 'a' }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, id: '../pet' }).ok).toBe(false);
  });

  it('rejects missing licence, version and name', () => {
    expect(parsePetPackManifest({ ...BASE, license: '' }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, version: '' }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, name: '' }).ok).toBe(false);
  });

  it('rejects out-of-range canvas and anchor', () => {
    expect(parsePetPackManifest({ ...BASE, canvas: { width: 32, height: 256 } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, canvas: { width: 256, height: 4096 } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, anchor: { x: 500, y: 10 } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, anchor: { x: -1, y: 10 } }).ok).toBe(false);
  });

  it('requires idle and known action keys', () => {
    expect(parsePetPackManifest({ ...BASE, actions: { thinking: ['a.webm'] } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, actions: { idle: ['a.webm'], dance: ['a.webm'] } }).ok).toBe(
      false,
    );
  });

  it('accepts detail-specific acting clips', () => {
    const result = parsePetPackManifest({
      ...BASE,
      actions: { idle: ['a.webm'], acting_edit: ['b.webm'], sleep_loop: ['c.webm'] },
    });
    expect(result.ok).toBe(true);
  });

  it('rejects unsafe or non-asset file names', () => {
    expect(parsePetPackManifest({ ...BASE, actions: { idle: ['../evil.webm'] } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, actions: { idle: ['run.exe'] } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, actions: { idle: ['index.html'] } }).ok).toBe(false);
    expect(parsePetPackManifest({ ...BASE, actions: { idle: ['/abs.webm'] } }).ok).toBe(false);
  });
});

describe('findPackRoot', () => {
  it('accepts pack.json at the archive root', () => {
    const result = findPackRoot(['pack.json', 'idle.webm']);
    expect(result.ok && result.value.root).toBe('');
  });

  it('accepts a single top-level folder', () => {
    const result = findPackRoot(['my-pet/pack.json', 'my-pet/idle.webm']);
    expect(result.ok && result.value.root).toBe('my-pet/');
  });

  it('rejects missing and duplicate manifests', () => {
    expect(findPackRoot(['idle.webm']).ok).toBe(false);
    expect(findPackRoot(['pack.json', 'a/pack.json']).ok).toBe(false);
  });

  it('rejects files outside the pack folder', () => {
    expect(findPackRoot(['my-pet/pack.json', 'other/idle.webm']).ok).toBe(false);
  });

  it('allows subfolders when pack.json is at the root', () => {
    const result = findPackRoot(['pack.json', 'frames/idle.webm']);
    expect(result.ok && result.value.root).toBe('');
  });
});

describe('validatePackEntries', () => {
  it('accepts a complete pack', () => {
    expect(
      validatePackEntries(['pack.json', 'frames/idle-0.webp', 'frames/think.webm'], BASE).ok,
    ).toBe(true);
  });

  it('rejects missing referenced assets', () => {
    const result = validatePackEntries(['pack.json', 'frames/idle-0.webp'], BASE);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('缺少素材文件');
  });

  it('allows unreferenced documentation but rejects other files', () => {
    expect(
      validatePackEntries(
        ['pack.json', 'frames/idle-0.webp', 'frames/think.webm', 'README.md'],
        BASE,
      ).ok,
    ).toBe(true);
    const exe = validatePackEntries(
      ['pack.json', 'frames/idle-0.webp', 'frames/think.webm', 'tool.exe'],
      BASE,
    );
    expect(exe.ok).toBe(false);
    const json = validatePackEntries(
      ['pack.json', 'frames/idle-0.webp', 'frames/think.webm', 'other.json'],
      BASE,
    );
    expect(json.ok).toBe(false);
  });
});
