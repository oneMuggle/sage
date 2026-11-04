import { deflateRawSync } from 'node:zlib';

import { describe, expect, it } from 'vitest';

import {
  crc32,
  decodeZipName,
  isSafeZipEntryName,
  readZip,
  writeZip,
  ZipReadError,
} from '../pet/zip';

const LIMITS = { maxEntries: 16, maxFileBytes: 1024 * 1024, maxTotalBytes: 4 * 1024 * 1024 };

interface RawEntry {
  name: string | Buffer;
  data: Buffer;
  method?: 0 | 8;
  flags?: number;
  externalAttrs?: number;
  crc?: number;
}

/** Minimal stored/deflated zip builder that allows intentionally bad names. */
function rawZip(entries: RawEntry[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.isBuffer(entry.name) ? entry.name : Buffer.from(entry.name, 'utf8');
    const method = entry.method ?? 0;
    const payload = method === 8 ? deflateRawSync(entry.data) : entry.data;
    const flags = entry.flags ?? 0x800;
    const crc = entry.crc ?? crc32(entry.data);

    const local = Buffer.alloc(30 + name.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(flags, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(payload.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    name.copy(local, 30);

    const central = Buffer.alloc(46 + name.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(flags, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(payload.length, 20);
    central.writeUInt32LE(entry.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(entry.externalAttrs ?? 0, 38);
    central.writeUInt32LE(offset, 42);
    name.copy(central, 46);

    locals.push(local, payload);
    centrals.push(central);
    offset += local.length + payload.length;
  }
  const cd = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cd.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, eocd]);
}

describe('zip write/read round-trip', () => {
  it('preserves UTF-8 entry names and bytes', () => {
    const zip = writeZip([
      { name: '我的宠物/pack.json', data: Buffer.from('{"id":"my-pet"}') },
      { name: '我的宠物/待机.webm', data: Buffer.from([1, 2, 3, 4]) },
    ]);
    const entries = readZip(zip, LIMITS);
    expect(entries.map((entry) => entry.name)).toEqual([
      '我的宠物/pack.json',
      '我的宠物/待机.webm',
    ]);
    expect(entries[1]!.data).toEqual(Buffer.from([1, 2, 3, 4]));
  });

  it('reads deflated entries', () => {
    const data = Buffer.from('hello '.repeat(100));
    const entries = readZip(rawZip([{ name: 'a.txt', data, method: 8 }]), LIMITS);
    expect(entries[0]!.data.toString()).toBe(data.toString());
  });
});

describe('zip reader hardening', () => {
  it('rejects a missing EOCD', () => {
    expect(() => readZip(Buffer.from('not a zip'), LIMITS)).toThrow(ZipReadError);
  });

  it('rejects path traversal entries', () => {
    expect(() => readZip(rawZip([{ name: '../evil.webm', data: Buffer.from('x') }]), LIMITS)).toThrow(
      /非法条目路径/,
    );
  });

  it('rejects absolute and backslash names', () => {
    expect(() => readZip(rawZip([{ name: '/etc/passwd', data: Buffer.from('x') }]), LIMITS)).toThrow(
      ZipReadError,
    );
    expect(() =>
      readZip(rawZip([{ name: 'dir\\evil.webm', data: Buffer.from('x') }]), LIMITS),
    ).toThrow(ZipReadError);
  });

  it('rejects duplicate names', () => {
    expect(() =>
      readZip(
        rawZip([
          { name: 'a.webm', data: Buffer.from('1') },
          { name: 'a.webm', data: Buffer.from('2') },
        ]),
        LIMITS,
      ),
    ).toThrow(/重复条目/);
  });

  it('rejects symlink entries', () => {
    expect(() =>
      readZip(
        rawZip([{ name: 'link.webm', data: Buffer.from('x'), externalAttrs: (0o120000 << 16) >>> 0 }]),
        LIMITS,
      ),
    ).toThrow(/符号链接/);
  });

  it('rejects CRC mismatches', () => {
    expect(() =>
      readZip(rawZip([{ name: 'a.webm', data: Buffer.from('x'), crc: 0x12345678 }]), LIMITS),
    ).toThrow(/CRC/);
  });

  it('enforces per-entry and total size limits', () => {
    const big = Buffer.alloc(64);
    expect(() =>
      readZip(rawZip([{ name: 'a.webm', data: big }]), { ...LIMITS, maxFileBytes: 32 }),
    ).toThrow(/条目过大/);
    expect(() =>
      readZip(
        rawZip([
          { name: 'a.webm', data: big },
          { name: 'b.webm', data: big },
        ]),
        { ...LIMITS, maxTotalBytes: 100 },
      ),
    ).toThrow(/总大小超限/);
  });

  it('rejects entry-count limits', () => {
    expect(() =>
      readZip(rawZip([{ name: 'a.webm', data: Buffer.from('x') }]), { ...LIMITS, maxEntries: 0 }),
    ).toThrow(/条目过多/);
  });

  it('refuses unsafe names on write', () => {
    expect(() => writeZip([{ name: '../x.webm', data: Buffer.from('x') }])).toThrow(/非法条目路径/);
  });
});

describe('entry name decoding', () => {
  it('decodes GBK names when the UTF-8 flag is absent', () => {
    // "测试.webm" in GBK, no UTF-8 flag (Windows Explorer behaviour).
    const gbk = Buffer.from([0xb2, 0xe2, 0xca, 0xd4, 0x2e, 0x77, 0x65, 0x62, 0x6d]);
    expect(decodeZipName(gbk, false)).toBe('测试.webm');
  });

  it('accepts safe relative names only', () => {
    expect(isSafeZipEntryName('frames/a.webp')).toBe(true);
    expect(isSafeZipEntryName('a.webm')).toBe(true);
    expect(isSafeZipEntryName('a/../b.webm')).toBe(false);
    expect(isSafeZipEntryName('./a.webm')).toBe(false);
    expect(isSafeZipEntryName('')).toBe(false);
  });
});
