import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import {
  deleteUserPack,
  exportPackZip,
  importPackZip,
  listUserPacks,
  petPacksDir,
} from '../pet/packStore';
import { readZip, writeZip } from '../pet/zip';

const MANIFEST = {
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

function packZip(manifest: Record<string, unknown> = MANIFEST): Buffer {
  return writeZip([
    { name: 'my-pet/pack.json', data: Buffer.from(JSON.stringify(manifest)) },
    { name: 'my-pet/frames/idle-0.webp', data: Buffer.from([1, 2, 3]) },
    { name: 'my-pet/frames/think.webm', data: Buffer.from([4, 5, 6]) },
  ]);
}

const tempDirs: string[] = [];

function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'pet-pack-'));
  tempDirs.push(dir);
  return dir;
}

function writeZipFile(dir: string, name: string, zip: Buffer): string {
  const file = join(dir, name);
  writeFileSync(file, zip);
  return file;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe('pet pack import', () => {
  it('extracts a pack into <packsDir>/<id> and lists it', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zipPath = writeZipFile(root, 'pack.zip', packZip());

    const result = importPackZip(packsDir, zipPath);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.manifest.id).toBe('my-pet');
    expect(existsSync(join(packsDir, 'my-pet', 'frames', 'idle-0.webp'))).toBe(true);

    const packs = listUserPacks(packsDir);
    expect(packs).toHaveLength(1);
    expect(packs[0]!.manifest.name).toBe('小叶灵');
  });

  it('accepts pack.json at the zip root with nested asset folders', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zip = writeZip([
      { name: 'pack.json', data: Buffer.from(JSON.stringify(MANIFEST)) },
      { name: 'frames/idle-0.webp', data: Buffer.from([1]) },
      { name: 'frames/think.webm', data: Buffer.from([2]) },
    ]);
    const result = importPackZip(packsDir, writeZipFile(root, 'root.zip', zip));
    expect(result.ok).toBe(true);
    expect(existsSync(join(packsDir, 'my-pet', 'frames', 'think.webm'))).toBe(true);
  });

  it('refuses a duplicate id and leaves the existing pack untouched', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zipPath = writeZipFile(root, 'pack.zip', packZip());
    expect(importPackZip(packsDir, zipPath).ok).toBe(true);

    const second = importPackZip(packsDir, zipPath);
    expect(second.ok).toBe(false);
    if (!second.ok) expect(second.error).toContain('已存在同名动画包');
    expect(readdirSync(packsDir)).toEqual(['my-pet']);
  });

  it('rejects a manifest that references missing assets and writes nothing', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zip = writeZip([
      { name: 'my-pet/pack.json', data: Buffer.from(JSON.stringify(MANIFEST)) },
      { name: 'my-pet/frames/idle-0.webp', data: Buffer.from([1]) },
    ]);
    const result = importPackZip(packsDir, writeZipFile(root, 'bad.zip', zip));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('缺少素材文件');
    expect(existsSync(join(packsDir, 'my-pet'))).toBe(false);
    const leftovers = existsSync(packsDir)
      ? readdirSync(packsDir).filter((name) => name.startsWith('.staging'))
      : [];
    expect(leftovers).toEqual([]);
  });

  it('rejects a manifest that tries to escape the pack directory', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zip = writeZip([
      {
        name: 'my-pet/pack.json',
        data: Buffer.from(
          JSON.stringify({ ...MANIFEST, actions: { idle: ['../evil.webm'] } }),
        ),
      },
    ]);
    const result = importPackZip(packsDir, writeZipFile(root, 'evil.zip', zip));
    expect(result.ok).toBe(false);
  });

  it('reports invalid JSON and invalid zips as errors', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const notZip = writeZipFile(root, 'not.zip', Buffer.from('nope'));
    expect(importPackZip(packsDir, notZip).ok).toBe(false);
  });
});

describe('pet pack export', () => {
  it('round-trips an imported pack through export and re-import', () => {
    const root = tempDir();
    const sourceDir = petPacksDir(join(root, 'a'));
    const targetDir = petPacksDir(join(root, 'b'));
    const zipPath = writeZipFile(root, 'pack.zip', packZip());
    expect(importPackZip(sourceDir, zipPath).ok).toBe(true);

    const exportPath = join(root, 'exported.zip');
    const exported = exportPackZip(sourceDir, 'my-pet', exportPath);
    expect(exported.ok).toBe(true);
    if (!exported.ok) return;

    const entries = readZip(readFileSync(exportPath), {
      maxEntries: 512,
      maxFileBytes: 64 * 1024 * 1024,
      maxTotalBytes: 256 * 1024 * 1024,
    });
    expect(entries.map((entry) => entry.name).sort()).toEqual([
      'my-pet/frames/idle-0.webp',
      'my-pet/frames/think.webm',
      'my-pet/pack.json',
    ]);

    const reimport = importPackZip(targetDir, exportPath);
    expect(reimport.ok).toBe(true);
  });

  it('rejects exporting built-in or unknown ids', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    expect(exportPackZip(packsDir, 'dafeiyu', join(root, 'out.zip')).ok).toBe(false);
    expect(exportPackZip(packsDir, 'nope', join(root, 'out.zip')).ok).toBe(false);
  });
});

describe('pet pack delete', () => {
  it('deletes a user pack but refuses built-in ids', () => {
    const root = tempDir();
    const packsDir = petPacksDir(root);
    const zipPath = writeZipFile(root, 'pack.zip', packZip());
    expect(importPackZip(packsDir, zipPath).ok).toBe(true);

    expect(deleteUserPack(packsDir, 'dafeiyu').ok).toBe(false);
    expect(deleteUserPack(packsDir, 'my-pet').ok).toBe(true);
    expect(existsSync(join(packsDir, 'my-pet'))).toBe(false);
    expect(listUserPacks(packsDir)).toEqual([]);
  });
});
