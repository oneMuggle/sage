/**
 * Pet pack manifest (pack.json) validation — pure functions, no I/O.
 *
 * Imported packs are untrusted input. The renderer only ever sees the
 * normalized manifest returned from here; anything that could reference a
 * path outside the pack directory, execute a script, or blow up the pet
 * renderer is rejected before extraction.
 */
import { extname } from 'node:path';

import type { PetPackManifest } from './types';
import { isSafeZipEntryName } from './zip';

export const PET_PACK_LIMITS = {
  maxZipBytes: 320 * 1024 * 1024,
  maxEntries: 512,
  maxFileBytes: 64 * 1024 * 1024,
  maxTotalBytes: 256 * 1024 * 1024,
  maxManifestBytes: 1024 * 1024,
  maxFilesPerAction: 64,
  maxNameChars: 60,
  maxVersionChars: 32,
  maxLicenseChars: 120,
  maxSourceChars: 500,
  canvasMin: 64,
  canvasMax: 2048,
} as const;

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,31}$/;
const RESERVED_IDS = new Set(['dafeiyu']);

const DETAILS = ['bash', 'edit', 'read', 'web', 'mcp', 'office', 'other'] as const;
const ACTION_KEYS = new Set([
  'idle',
  'sleeping',
  'thinking',
  'acting',
  'observing',
  'retry',
  'waiting',
  'done',
  'error',
  'click',
  'pat',
  'angry',
  'drag',
  'sleep_start',
  'sleep_loop',
  'sleep_end',
  'balance',
  ...DETAILS.map((detail) => `acting_${detail}`),
]);

const ASSET_EXTENSIONS = new Set(['.webm', '.mp4', '.webp', '.png', '.jpg', '.jpeg', '.gif', '.apng']);
const DOC_EXTENSIONS = new Set(['.txt', '.md']);

export type PackValidation<T> = { ok: true; value: T } | { ok: false; error: string };

function fail<T>(error: string): PackValidation<T> {
  return { ok: false, error };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Shape check only; reserved ids (built-in packs) are rejected separately. */
export function isValidPackIdShape(id: unknown): id is string {
  return typeof id === 'string' && ID_PATTERN.test(id);
}

export function isImportablePackId(id: unknown): id is string {
  return isValidPackIdShape(id) && !RESERVED_IDS.has(id);
}

function safePath(value: unknown, extensions: Set<string>): string | null {
  if (typeof value !== 'string' || value.length > 255) return null;
  if (!isSafeZipEntryName(value)) return null;
  if (!extensions.has(extname(value).toLowerCase())) return null;
  return value;
}

function nonEmptyString(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > max) return null;
  return trimmed;
}

export function parsePetPackManifest(raw: unknown): PackValidation<PetPackManifest> {
  if (!isRecord(raw)) return fail('pack.json 必须是对象');
  const { id, name, version, license, source, canvas, anchor, actions } = raw;

  if (!isImportablePackId(id)) return fail('id 只能包含小写字母/数字/短横线（2–32 位），且不能与内置包同名');
  const cleanName = nonEmptyString(name, PET_PACK_LIMITS.maxNameChars);
  if (!cleanName) return fail('name 不能为空，且不超过 60 字');
  const cleanVersion = nonEmptyString(version, PET_PACK_LIMITS.maxVersionChars);
  if (!cleanVersion) return fail('version 不能为空，且不超过 32 字');
  const cleanLicense = nonEmptyString(license, PET_PACK_LIMITS.maxLicenseChars);
  if (!cleanLicense) return fail('license 不能为空，且不超过 120 字');

  let cleanSource: string | undefined;
  if (source !== undefined && source !== null && source !== '') {
    const candidate = nonEmptyString(source, PET_PACK_LIMITS.maxSourceChars);
    if (!candidate) return fail('source 超过 500 字');
    if (!/^https?:\/\//i.test(candidate)) return fail('source 必须是 http(s) 链接');
    cleanSource = candidate;
  }

  if (!isRecord(canvas)) return fail('canvas 必须是对象');
  const width = canvas.width;
  const height = canvas.height;
  if (
    !isFiniteNumber(width) ||
    !isFiniteNumber(height) ||
    width < PET_PACK_LIMITS.canvasMin ||
    height < PET_PACK_LIMITS.canvasMin ||
    width > PET_PACK_LIMITS.canvasMax ||
    height > PET_PACK_LIMITS.canvasMax
  ) {
    return fail('canvas.width/height 必须是 64–2048 的数字');
  }

  if (!isRecord(anchor)) return fail('anchor 必须是对象');
  const anchorX = anchor.x;
  const anchorY = anchor.y;
  if (
    !isFiniteNumber(anchorX) ||
    !isFiniteNumber(anchorY) ||
    anchorX < 0 ||
    anchorY < 0 ||
    anchorX > width ||
    anchorY > height
  ) {
    return fail('anchor.x/y 必须位于 canvas 范围内');
  }

  if (!isRecord(actions)) return fail('actions 必须是对象');
  const cleanActions: Record<string, string[]> = {};
  for (const [key, files] of Object.entries(actions)) {
    if (!ACTION_KEYS.has(key)) return fail(`未知动作：${key}`);
    if (!Array.isArray(files) || files.length === 0 || files.length > PET_PACK_LIMITS.maxFilesPerAction)
      return fail(`动作 ${key} 需要 1–64 个文件`);
    const cleanFiles: string[] = [];
    for (const file of files) {
      const clean = safePath(file, ASSET_EXTENSIONS);
      if (!clean) return fail(`动作 ${key} 中的文件非法：${String(file)}`);
      cleanFiles.push(clean);
    }
    cleanActions[key] = cleanFiles;
  }
  if (!cleanActions.idle || cleanActions.idle.length === 0)
    return fail('actions.idle 至少需要一个待机动画');

  return {
    ok: true,
    value: {
      id,
      name: cleanName,
      version: cleanVersion,
      license: cleanLicense,
      ...(cleanSource ? { source: cleanSource } : {}),
      canvas: { width, height },
      anchor: { x: anchorX, y: anchorY },
      actions: cleanActions,
    },
  };
}

export interface PackRoot {
  /** '' when pack.json sits at the archive root, otherwise 'folder/'. */
  root: string;
}

/**
 * Locate the single pack.json at archive root or one folder deep. Every
 * other entry must live under that folder.
 */
export function findPackRoot(names: readonly string[]): PackValidation<PackRoot> {
  const candidates = names.filter((name) => name === 'pack.json' || /^[^/]+\/pack\.json$/.test(name));
  if (candidates.length === 0) return fail('zip 中找不到 pack.json');
  if (candidates.length > 1) return fail('zip 中包含多个 pack.json');
  const manifestEntry = candidates[0]!;
  const root = manifestEntry.slice(0, manifestEntry.length - 'pack.json'.length);
  for (const name of names) {
    if (name.endsWith('/')) continue;
    if (root && !name.startsWith(root)) return fail(`文件不在包目录内：${name}`);
    // Root-level packs may still use subfolders (e.g. frames/idle.webm); only
    // the relative path itself is safety-checked. A second pack.json deeper in
    // the tree is not a candidate here and is rejected by validatePackEntries.
    const relative = root ? name.slice(root.length) : name;
    if (!isSafeZipEntryName(relative)) return fail(`非法条目路径：${name}`);
  }
  return { ok: true, value: { root } };
}

/**
 * Cross-check the manifest against the archive file list (names relative to
 * the pack root). Unreferenced files are rejected unless they are plain
 * documentation, so a pack can never smuggle extra executables or HTML.
 */
export function validatePackEntries(
  relativeNames: readonly string[],
  manifest: PetPackManifest,
): PackValidation<true> {
  const present = new Set(relativeNames);
  const referenced = new Set<string>();
  for (const files of Object.values(manifest.actions)) {
    for (const file of files) {
      referenced.add(file);
      if (!present.has(file)) return fail(`缺少素材文件：${file}`);
    }
  }
  for (const name of relativeNames) {
    if (name === 'pack.json') continue;
    if (referenced.has(name)) continue;
    if (name.endsWith('.json')) return fail(`只允许一个 pack.json：${name}`);
    if (!DOC_EXTENSIONS.has(extname(name).toLowerCase()))
      return fail(`存在未引用的文件：${name}`);
  }
  return { ok: true, value: true };
}
