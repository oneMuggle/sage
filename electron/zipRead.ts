/**
 * P2 (2026-09-18): Minimal read-only ZIP extractor for pet pack imports
 * (docs/plans/2026-09-18_desktop-pet-design.md §3).
 *
 * Why hand-rolled: the zero-new-dependency gate (31-win7-lts.md §2 门禁3)
 * rules out jszip/adm-zip, and the only existing zip code in-repo is the
 * backend-generated diagnostic bundle (never parsed in Electron). This
 * module reads the End Of Central Directory + Central Directory only
 * (local headers just to locate data), and is intentionally strict:
 *
 *   - methods 0 (stored) / 8 (deflate) only; encryption bit → reject
 *   - ZIP64 → reject (pet packs can't legitimately need it)
 *   - symlink entries (external attrs) → reject
 *   - absolute / drive / backslash / '..' / duplicate names → reject
 *   - per-entry declared AND actual inflated size capped by caller
 *     (maxFileBytes / maxTotalBytes / maxEntries) — zip-bomb guard
 */
import { inflateRawSync } from 'node:zlib';

export interface ZipEntry {
  name: string;
  data: Buffer;
}

export interface ZipReadLimits {
  maxEntries: number;
  maxFileBytes: number;
  maxTotalBytes: number;
}

const EOCD_SIGNATURE = 0x06054b50;
const EOCD64_LOCATOR_SIGNATURE = 0x07064b50;
const CD_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;
const MIN_EOCD_SIZE = 22;
const MAX_EOCD_COMMENT = 65535;
const ZIP64_MARKER = 0xffffffff;
const S_IFMT = 0o170000;
const S_IFLNK = 0o120000;

export class ZipReadError extends Error {}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c;
  }
  return table;
})();

export function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]!) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function findEocd(buf: Buffer): number {
  const start = Math.max(0, buf.length - MIN_EOCD_SIZE - MAX_EOCD_COMMENT);
  for (let i = buf.length - MIN_EOCD_SIZE; i >= start; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIGNATURE) return i;
  }
  return -1;
}

function isSafeEntryName(name: string): boolean {
  if (!name || name.includes('\\') || /^[a-zA-Z]:/.test(name) || name.startsWith('/'))
    return false;
  return name.split('/').every((segment) => segment !== '' || name.endsWith('/')) &&
    !name.split('/').includes('..');
}

/** Parse + fully validate a zip archive; returns entries (directories omitted). */
export function readZip(buf: Buffer, limits: ZipReadLimits): ZipEntry[] {
  const eocdAt = findEocd(buf);
  if (eocdAt === -1) throw new ZipReadError('不是有效的 zip 文件（找不到 EOCD）');
  if (eocdAt >= 4 && buf.readUInt32LE(eocdAt - 4) === EOCD64_LOCATOR_SIGNATURE)
    throw new ZipReadError('不支持 ZIP64');
  const totalEntries = buf.readUInt16LE(eocdAt + 10);
  const cdSize = buf.readUInt32LE(eocdAt + 12);
  const cdOffset = buf.readUInt32LE(eocdAt + 16);
  if (totalEntries === 0xffff || cdSize === ZIP64_MARKER || cdOffset === ZIP64_MARKER)
    throw new ZipReadError('不支持 ZIP64');
  if (cdOffset + cdSize > eocdAt) throw new ZipReadError('中央目录越界');
  if (totalEntries === 0) throw new ZipReadError('zip 为空');
  if (totalEntries > limits.maxEntries)
    throw new ZipReadError(`条目过多：${totalEntries} > ${limits.maxEntries}`);

  const entries: ZipEntry[] = [];
  const seen = new Set<string>();
  let total = 0;
  let at = cdOffset;
  for (let i = 0; i < totalEntries; i++) {
    if (at + 46 > buf.length || buf.readUInt32LE(at) !== CD_SIGNATURE)
      throw new ZipReadError(`中央目录条目 ${i} 损坏`);
    const flags = buf.readUInt16LE(at + 8);
    const method = buf.readUInt16LE(at + 10);
    const crc = buf.readUInt32LE(at + 16);
    const compSize = buf.readUInt32LE(at + 20);
    const uncompSize = buf.readUInt32LE(at + 24);
    const nameLen = buf.readUInt16LE(at + 28);
    const extraLen = buf.readUInt16LE(at + 30);
    const commentLen = buf.readUInt16LE(at + 32);
    const externalAttrs = buf.readUInt32LE(at + 38);
    const localOffset = buf.readUInt32LE(at + 42);
    const name = buf.subarray(at + 46, at + 46 + nameLen).toString('utf8');
    at += 46 + nameLen + extraLen + commentLen;
    if (at > eocdAt) throw new ZipReadError('中央目录条目越界');

    if (flags & 0x1) throw new ZipReadError(`不支持加密条目：${name}`);
    if (compSize === ZIP64_MARKER || uncompSize === ZIP64_MARKER || localOffset === ZIP64_MARKER)
      throw new ZipReadError(`不支持 ZIP64 条目：${name}`);
    if (((externalAttrs >>> 16) & S_IFMT) === S_IFLNK)
      throw new ZipReadError(`拒绝符号链接条目：${name}`);
    if (name.endsWith('/')) continue; // directory entry
    if (!isSafeEntryName(name)) throw new ZipReadError(`非法条目路径：${name}`);
    if (seen.has(name)) throw new ZipReadError(`重复条目：${name}`);
    seen.add(name);
    if (method !== 0 && method !== 8) throw new ZipReadError(`不支持压缩方法 ${method}：${name}`);
    if (uncompSize > limits.maxFileBytes || compSize > limits.maxFileBytes)
      throw new ZipReadError(`条目过大：${name}`);
    total += uncompSize;
    if (total > limits.maxTotalBytes)
      throw new ZipReadError(`解压总大小超限：> ${limits.maxTotalBytes} 字节`);

    if (localOffset + 30 > buf.length || buf.readUInt32LE(localOffset) !== LOCAL_SIGNATURE)
      throw new ZipReadError(`本地头损坏：${name}`);
    const localNameLen = buf.readUInt16LE(localOffset + 26);
    const localExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataAt = localOffset + 30 + localNameLen + localExtraLen;
    if (dataAt + compSize > buf.length) throw new ZipReadError(`条目数据越界：${name}`);
    const raw = buf.subarray(dataAt, dataAt + compSize);
    let data: Buffer;
    if (method === 0) {
      if (compSize !== uncompSize) throw new ZipReadError(`stored 条目尺寸不符：${name}`);
      data = Buffer.from(raw);
    } else {
      try {
        data = inflateRawSync(raw, { maxOutputLength: limits.maxFileBytes });
      } catch (error) {
        throw new ZipReadError(`解压失败：${name}（${String(error)}）`);
      }
      if (data.length !== uncompSize)
        throw new ZipReadError(`解压尺寸与声明不符：${name}（${data.length} ≠ ${uncompSize}）`);
    }
    if (crc32(data) !== crc) throw new ZipReadError(`CRC 校验失败：${name}`);
    entries.push({ name, data });
  }
  return entries;
}
