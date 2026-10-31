/**
 * User pet pack store — import/export/list/delete under `<userData>/pets/`.
 *
 * Import is a two-phase operation: the archive is validated entirely in
 * memory, extracted into a hidden staging directory, then renamed into
 * place. A failed import never leaves a half-written pack behind.
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

import { logger } from '../logger';
import {
  PET_PACK_LIMITS,
  findPackRoot,
  isImportablePackId,
  isValidPackIdShape,
  parsePetPackManifest,
  validatePackEntries,
} from './packManifest';
import type { PetPackManifest } from './types';
import { readZip, writeZip, ZipReadError, type ZipWriteEntry } from './zip';

export function petPacksDir(userDataDir: string): string {
  return join(userDataDir, 'pets');
}

export interface InstalledPetPack {
  manifest: PetPackManifest;
  dir: string;
}

export type ImportResult = { ok: true; manifest: PetPackManifest } | { ok: false; error: string };
export type ExportResult = { ok: true; path: string } | { ok: false; error: string };
export type DeleteResult = { ok: true } | { ok: false; error: string };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

function readManifestFile(file: string): ReturnType<typeof parsePetPackManifest> {
  try {
    return parsePetPackManifest(JSON.parse(stripBom(readFileSync(file, 'utf8'))));
  } catch {
    return { ok: false, error: 'pack.json 不是合法 JSON' };
  }
}

/** Installed user packs, sorted by id. Invalid folders are skipped. */
export function listUserPacks(packsDir: string): InstalledPetPack[] {
  let names: string[];
  try {
    names = readdirSync(packsDir);
  } catch {
    return [];
  }
  const packs: InstalledPetPack[] = [];
  for (const name of names.sort()) {
    if (!isValidPackIdShape(name)) continue;
    const dir = join(packsDir, name);
    try {
      if (!statSync(dir).isDirectory()) continue;
      const parsed = readManifestFile(join(dir, 'pack.json'));
      if (!parsed.ok) {
        logger.warn('pet: skipping invalid user pack', { id: name, reason: parsed.error });
        continue;
      }
      if (parsed.value.id !== name) {
        logger.warn('pet: skipping pack whose id does not match its folder', {
          folder: name,
          id: parsed.value.id,
        });
        continue;
      }
      packs.push({ manifest: parsed.value, dir });
    } catch {
      // Vanished between readdir and stat — ignore.
    }
  }
  return packs;
}

export function importPackZip(packsDir: string, zipPath: string): ImportResult {
  try {
    const zipStat = statSync(zipPath);
    if (!zipStat.isFile()) return { ok: false, error: '选择的路径不是文件' };
    if (zipStat.size > PET_PACK_LIMITS.maxZipBytes) {
      return { ok: false, error: `动画包超过 ${PET_PACK_LIMITS.maxZipBytes / 1024 / 1024} MB 上限` };
    }
    const entries = readZip(readFileSync(zipPath), {
      maxEntries: PET_PACK_LIMITS.maxEntries,
      maxFileBytes: PET_PACK_LIMITS.maxFileBytes,
      maxTotalBytes: PET_PACK_LIMITS.maxTotalBytes,
    });

    const names = entries.map((entry) => entry.name);
    const rootResult = findPackRoot(names);
    if (!rootResult.ok) return rootResult;
    const { root } = rootResult.value;
    const manifestEntry = entries.find((entry) => entry.name === `${root}pack.json`);
    if (!manifestEntry) return { ok: false, error: 'zip 中找不到 pack.json' };
    if (manifestEntry.data.length > PET_PACK_LIMITS.maxManifestBytes)
      return { ok: false, error: 'pack.json 超过 1 MB' };

    let raw: unknown;
    try {
      raw = JSON.parse(stripBom(manifestEntry.data.toString('utf8')));
    } catch {
      return { ok: false, error: 'pack.json 不是合法 JSON' };
    }
    const parsed = parsePetPackManifest(raw);
    if (!parsed.ok) return parsed;
    const manifest = parsed.value;

    const relativeNames = names.map((name) => name.slice(root.length));
    const validated = validatePackEntries(relativeNames, manifest);
    if (!validated.ok) return validated;

    const target = join(packsDir, manifest.id);
    if (existsSync(target)) {
      return {
        ok: false,
        error: `已存在同名动画包「${manifest.id}」，请先在设置中删除，或修改 pack.json 的 id`,
      };
    }

    mkdirSync(packsDir, { recursive: true });
    const staging = join(
      packsDir,
      `.staging-${process.pid}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    );
    try {
      mkdirSync(staging, { recursive: true });
      for (const entry of entries) {
        const relative = entry.name.slice(root.length);
        const dest = join(staging, ...relative.split('/'));
        mkdirSync(dirname(dest), { recursive: true });
        writeFileSync(dest, entry.data);
      }
      renameSync(staging, target);
    } catch (error) {
      try {
        rmSync(staging, { recursive: true, force: true });
      } catch {
        // Staging cleanup is best-effort; the import error below is what matters.
      }
      return { ok: false, error: `写入动画包失败：${errorMessage(error)}` };
    }
    return { ok: true, manifest };
  } catch (error) {
    if (error instanceof ZipReadError) return { ok: false, error: error.message };
    return { ok: false, error: errorMessage(error) };
  }
}

/** Export a user pack as `<id>/pack.json` + referenced assets (stored zip). */
export function exportPackZip(packsDir: string, id: string, destPath: string): ExportResult {
  if (!isImportablePackId(id)) return { ok: false, error: '非法动画包 id' };
  const dir = join(packsDir, id);
  const manifestPath = join(dir, 'pack.json');
  if (!existsSync(manifestPath)) return { ok: false, error: '动画包不存在' };
  const parsed = readManifestFile(manifestPath);
  if (!parsed.ok) return parsed;

  const files = Array.from(new Set(Object.values(parsed.value.actions).flat())).sort();
  const entries: ZipWriteEntry[] = [];
  let total = 0;
  try {
    const manifestBytes = readFileSync(manifestPath);
    entries.push({ name: `${id}/pack.json`, data: manifestBytes });
    total += manifestBytes.length;
    for (const file of files) {
      const absolute = join(dir, ...file.split('/'));
      const fileStat = statSync(absolute);
      if (!fileStat.isFile()) return { ok: false, error: `素材不是普通文件：${file}` };
      if (fileStat.size > PET_PACK_LIMITS.maxFileBytes)
        return { ok: false, error: `素材超过单文件上限：${file}` };
      total += fileStat.size;
      if (total > PET_PACK_LIMITS.maxTotalBytes)
        return { ok: false, error: '动画包总大小超过 256 MB 上限' };
      entries.push({ name: `${id}/${file}`, data: readFileSync(absolute) });
    }
    const zip = writeZip(entries);
    mkdirSync(dirname(destPath), { recursive: true });
    writeFileSync(destPath, zip);
    return { ok: true, path: destPath };
  } catch (error) {
    return { ok: false, error: `导出失败：${errorMessage(error)}` };
  }
}

export function deleteUserPack(packsDir: string, id: string): DeleteResult {
  if (!isImportablePackId(id)) return { ok: false, error: '非法动画包 id' };
  const dir = join(packsDir, id);
  try {
    if (!statSync(dir).isDirectory()) return { ok: false, error: '动画包不存在' };
    rmSync(dir, { recursive: true, force: false });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: `删除失败：${errorMessage(error)}` };
  }
}
