/**
 * Minimal read/write ZIP support for pet pack import/export (2026-10-31).
 *
 * Why hand-rolled: pet packs are a user-facing archive format, but adding
 * jszip/adm-zip would be a new runtime dependency for a single feature. This
 * module implements only what the feature needs and is intentionally strict:
 *
 *   - methods 0 (stored) / 8 (deflate) only; encryption bit → reject
 *   - ZIP64 → reject (pet packs can't legitimately need it)
 *   - symlink entries (external attrs) → reject
 *   - absolute / drive / backslash / '..' / duplicate names → reject
 *   - per-entry declared AND actual inflated size capped by caller
 *     (maxFileBytes / maxTotalBytes / maxEntries) — zip-bomb guard
 *   - CRC-32 verified for every entry
 *
 * Export always uses method 0 (stored): pack assets are already compressed
 * video/image files, so deflating them again buys almost nothing.
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
const UTF8_FLAG = 0x800;
const MAX_UINT16 = 0xffff;

/** DOS timestamp for 1980-01-01 00:00:00 — deterministic export output. */
const DOS_TIME = 0;
const DOS_DATE = 0x0021;

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
    if (buf.readUInt32LE(i) !== EOCD_SIGNATURE) continue;
    // The comment length must match the remaining bytes; otherwise the
    // signature is a coincidental byte sequence inside somebody's comment.
    if (i + MIN_EOCD_SIZE + buf.readUInt16LE(i + 20) === buf.length) return i;
  }
  return -1;
}

/**
 * Decode a ZIP entry name.
 *
 * Windows Explorer's “send to → compressed folder” writes GBK names without
 * the UTF-8 flag on Chinese systems. Prefer UTF-8 only when the bytes are
 * valid UTF-8; otherwise fall back to GBK (full-ICU builds) and finally a
 * permissive UTF-8 decode so a weird archive cannot crash the importer.
 */
export function decodeZipName(bytes: Buffer, utf8Flag: boolean): string {
  if (utf8Flag) return bytes.toString('utf8');
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    try {
      return new TextDecoder('gbk').decode(bytes);
    } catch {
      return bytes.toString('utf8');
    }
  }
}

export function isSafeZipEntryName(name: string): boolean {
  if (!name || name.includes('\\') || name.includes('\0') || name.startsWith('/')) return false;
  if (/^[a-zA-Z]:/.test(name)) return false;
  const segments = name.split('/');
  return segments.every((segment) => segment !== '' && segment !== '.' && segment !== '..');
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
  if (totalEntries === MAX_UINT16 || cdSize === ZIP64_MARKER || cdOffset === ZIP64_MARKER)
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
    const name = decodeZipName(
      buf.subarray(at + 46, at + 46 + nameLen),
      (flags & UTF8_FLAG) !== 0,
    );
    at += 46 + nameLen + extraLen + commentLen;
    if (at > eocdAt) throw new ZipReadError('中央目录条目越界');

    if (flags & 0x1) throw new ZipReadError(`不支持加密条目：${name}`);
    if (compSize === ZIP64_MARKER || uncompSize === ZIP64_MARKER || localOffset === ZIP64_MARKER)
      throw new ZipReadError(`不支持 ZIP64 条目：${name}`);
    if (((externalAttrs >>> 16) & S_IFMT) === S_IFLNK)
      throw new ZipReadError(`拒绝符号链接条目：${name}`);
    if (name.endsWith('/')) continue; // directory entry
    if (!isSafeZipEntryName(name)) throw new ZipReadError(`非法条目路径：${name}`);
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
    const localFlags = buf.readUInt16LE(localOffset + 6);
    const localNameLen = buf.readUInt16LE(localOffset + 26);
    const localExtraLen = buf.readUInt16LE(localOffset + 28);
    const localName = decodeZipName(
      buf.subarray(localOffset + 30, localOffset + 30 + localNameLen),
      (localFlags & UTF8_FLAG) !== 0,
    );
    if (localName !== name) throw new ZipReadError(`本地头名称与中央目录不一致：${name}`);
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

export interface ZipWriteEntry {
  name: string;
  data: Buffer;
}

/**
 * Build a stored (method 0) ZIP archive. Names are written as UTF-8.
 * Callers are responsible for the total size staying below 4 GiB.
 */
export function writeZip(entries: ZipWriteEntry[]): Buffer {
  if (entries.length === 0) throw new ZipReadError('zip 为空');
  if (entries.length > MAX_UINT16) throw new ZipReadError('条目过多，无法写入 zip');
  const seen = new Set<string>();
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;

  for (const entry of entries) {
    if (!isSafeZipEntryName(entry.name))
      throw new ZipReadError(`非法条目路径：${entry.name}`);
    if (seen.has(entry.name)) throw new ZipReadError(`重复条目：${entry.name}`);
    seen.add(entry.name);
    if (entry.data.length > ZIP64_MARKER) throw new ZipReadError(`条目过大：${entry.name}`);

    const name = Buffer.from(entry.name, 'utf8');
    if (name.length > MAX_UINT16) throw new ZipReadError(`条目名过长：${entry.name}`);
    const crc = crc32(entry.data);

    const local = Buffer.alloc(30 + name.length);
    local.writeUInt32LE(LOCAL_SIGNATURE, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(UTF8_FLAG, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(entry.data.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    name.copy(local, 30);

    const central = Buffer.alloc(46 + name.length);
    central.writeUInt32LE(CD_SIGNATURE, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(UTF8_FLAG, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(DOS_TIME, 12);
    central.writeUInt16LE(DOS_DATE, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(entry.data.length, 20);
    central.writeUInt32LE(entry.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    name.copy(central, 46);

    locals.push(local, entry.data);
    centrals.push(central);
    offset += local.length + entry.data.length;
    if (offset > ZIP64_MARKER) throw new ZipReadError('zip 体积超限');
  }

  const cd = Buffer.concat(centrals);
  const eocd = Buffer.alloc(MIN_EOCD_SIZE);
  eocd.writeUInt32LE(EOCD_SIGNATURE, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cd.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20);
  return Buffer.concat([...locals, cd, eocd]);
}
