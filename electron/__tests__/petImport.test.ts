/**
 * P2 宠物包导入管线契约测试（docs/plans/2026-09-18_desktop-pet-design.md §3）。
 *
 * 覆盖两层：
 *  - electron/zipRead.ts：手工构造 zip 字节，断言安全拒绝路径
 *    （路径穿越 / symlink / 加密 / ZIP64 / 超限 / CRC 损坏 / 重复条目）
 *  - electron/petImport.ts：plan → quarantine → commit/discard 全链路，
 *    含同 id 冲突、清单校验、CSS 卫生、data URL 内联、孤儿隔离区清扫
 *
 * zip 构造器复用被测模块导出的 crc32，与真实打包工具（deflate 法 8、
 * 目录项、UTF-8 名）字节级一致。
 */
import { mkdtemp, readFile, utimes, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { deflateRawSync } from 'node:zlib';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  commitImport,
  discardImport,
  listInstalledPacks,
  planImportFromZip,
  removePack,
  sweepStaleQuarantine,
  type PetImportEnv,
} from '../petImport';
import { crc32, readZip } from '../zipRead';

// ─── zip 构造器（测试专用最小 writer）───────────────────────

interface ZipInput {
  name: string;
  data?: Buffer;
  method?: 0 | 8;
  /** external attrs 高 16 位放 st_mode；0o120777 构造 symlink 条目 */
  externalAttrs?: number;
  flags?: number;
  /** 篡改 CRC 模拟损坏条目 */
  corruptCrc?: boolean;
  /** 声明一个不符的 uncompSize（zip-bomb 样式） */
  fakeUncompSize?: number;
}

function buildZip(entries: ZipInput[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const e of entries) {
    const method = e.method ?? 8;
    const data = e.data ?? Buffer.alloc(0);
    const comp = method === 8 ? deflateRawSync(data) : data;
    const crc = (e.corruptCrc ? (crc32(data) ^ 0xbeef) >>> 0 : crc32(data)) >>> 0;
    const name = Buffer.from(e.name, 'utf8');
    const local = Buffer.alloc(30 + name.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(e.flags ?? 0, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(19752, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(comp.length, 18);
    local.writeUInt32LE(e.fakeUncompSize ?? data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    name.copy(local, 30);
    locals.push(local, comp);

    const central = Buffer.alloc(46 + name.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(e.flags ?? 0, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(19752, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(comp.length, 20);
    central.writeUInt32LE(e.fakeUncompSize ?? data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(e.externalAttrs ?? 0, 38);
    central.writeUInt32LE(offset, 42);
    name.copy(central, 46);
    centrals.push(central);
    offset += local.length + comp.length;
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

const LIMITS = { maxEntries: 64, maxFileBytes: 1024, maxTotalBytes: 4096 };

// ─── zipRead ────────────────────────────────────────────────

describe('zipRead', () => {
  it('happy path：stored + deflate 混合，目录条目跳过', () => {
    const zip = buildZip([
      { name: 'pet.json', data: Buffer.from('{"a":1}'), method: 8 },
      { name: 'animations/x.css', data: Buffer.from('.x{}'), method: 0 },
      { name: 'assets/', data: Buffer.alloc(0) },
    ]);
    const entries = readZip(zip, LIMITS);
    expect(entries.map((e) => e.name)).toEqual(['pet.json', 'animations/x.css']);
    expect(entries[0]!.data.toString()).toBe('{"a":1}');
  });

  it('路径穿越 / 绝对路径 / 反斜杠 / 盘符 → 拒绝', () => {
    for (const bad of ['../evil', '/etc/passwd', 'a\\b', 'C:\\Windows\\x', 'a//b', 'a/../b']) {
      expect(() => readZip(buildZip([{ name: bad, data: Buffer.from('x') }]), LIMITS)).toThrow(
        /非法条目路径/,
      );
    }
  });

  it('symlink 条目（external attrs S_IFLNK）→ 拒绝', () => {
    const zip = buildZip([
      { name: 'link', data: Buffer.from('/etc'), externalAttrs: ((0o120777 << 16) >>> 0) as number },
    ]);
    expect(() => readZip(zip, LIMITS)).toThrow(/符号链接/);
  });

  it('加密条目（flags bit0）→ 拒绝', () => {
    expect(() => readZip(buildZip([{ name: 'a', data: Buffer.from('x'), flags: 1 }]), LIMITS)).toThrow(
      /加密/,
    );
  });

  it('ZIP64 字段标记 → 拒绝', () => {
    expect(() =>
      readZip(buildZip([{ name: 'a', data: Buffer.from('x'), fakeUncompSize: 0xffffffff }]), LIMITS),
    ).toThrow(/ZIP64/);
  });

  it('声明大小超限（zip bomb 前置拦截）→ 拒绝', () => {
    expect(() =>
      readZip(buildZip([{ name: 'a', data: Buffer.from('x'), fakeUncompSize: 9999 }]), LIMITS),
    ).toThrow(/过大|超限/);
  });

  it('条目数 / 总大小超限 → 拒绝', () => {
    expect(() =>
      readZip(
        buildZip([
          { name: 'a', data: Buffer.from('x') },
          { name: 'b', data: Buffer.from('y') },
        ]),
        { ...LIMITS, maxEntries: 1 },
      ),
    ).toThrow(/条目过多/);
    const big = Buffer.alloc(3000, 1); // > maxTotalBytes 且每文件 < maxFileBytes(1024)? 3000>1024 → 单文件超限
    expect(() => readZip(buildZip([{ name: 'a', data: big }]), LIMITS)).toThrow(/过大|超限/);
  });

  it('CRC 损坏 / 解压尺寸不符 / 重复条目 / 非 zip → 拒绝', () => {
    expect(() =>
      readZip(buildZip([{ name: 'a', data: Buffer.from('hello'), corruptCrc: true }]), LIMITS),
    ).toThrow(/CRC/);
    expect(() =>
      readZip(
        buildZip([{ name: 'a', data: Buffer.from('hello'), fakeUncompSize: 4 }]),
        LIMITS,
      ),
    ).toThrow(/不符|CRC/);
    expect(() =>
      readZip(
        buildZip([
          { name: 'a', data: Buffer.from('x') },
          { name: 'a', data: Buffer.from('y') },
        ]),
        LIMITS,
      ),
    ).toThrow(/重复条目/);
    expect(() => readZip(Buffer.from('not a zip file at all'), LIMITS)).toThrow(/EOCD/);
  });
});

// ─── petImport ──────────────────────────────────────────────

const GOOD_MANIFEST = {
  id: 'panda-01',
  name: '小熊猫',
  author: 'tester',
  bodyClass: 'pet-body-panda-01',
  animations: { idle: 'pet-anim-panda-idle', thinking: 'pet-anim-panda-thinking' },
};

function goodPackZip(extra?: Record<string, string>): Buffer {
  const files: Record<string, string> = {
    'pet.json': JSON.stringify(GOOD_MANIFEST),
    'styles/main.css': '.pet-body-panda-01{width:100px}',
    ...extra,
  };
  return buildZip(
    Object.entries(files).map(([name, content]) => ({ name, data: Buffer.from(content) })),
  );
}

/** 1x1 PNG */
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

let env: PetImportEnv;
beforeEach(async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'pet-import-'));
  env = { petsDir: path.join(root, 'pets'), quarantineDir: path.join(root, 'quarantine') };
});

describe('planImportFromZip', () => {
  it('合法包 → 写隔离区并返回 token/files/conflict=false', async () => {
    const plan = await planImportFromZip(goodPackZip(), env);
    expect(plan.ok).toBe(true);
    if (!plan.ok) return;
    expect(plan.manifest.id).toBe('panda-01');
    expect(plan.files.map((f) => f.path).sort()).toEqual(['pet.json', 'styles/main.css']);
    expect(plan.conflict).toBe(false);
    const written = await readFile(path.join(env.quarantineDir, plan.token, 'pet.json'), 'utf8');
    expect(JSON.parse(written).name).toBe('小熊猫');
  });

  it('单一顶层目录包裹的包自动剥根', async () => {
    const zip = buildZip([
      { name: 'panda-01/pet.json', data: Buffer.from(JSON.stringify(GOOD_MANIFEST)) },
      { name: 'panda-01/main.css', data: Buffer.from('.x{}') },
    ]);
    const plan = await planImportFromZip(zip, env);
    expect(plan.ok && plan.files.map((f) => f.path).sort()).toEqual(['main.css', 'pet.json']);
  });

  it('缺 pet.json / 非法扩展名 / .exe → 拒绝且不留隔离区', async () => {
    const noManifest = buildZip([{ name: 'a.css', data: Buffer.from('.a{}') }]);
    expect((await planImportFromZip(noManifest, env)).ok).toBe(false);
    const exe = buildZip([
      { name: 'pet.json', data: Buffer.from(JSON.stringify(GOOD_MANIFEST)) },
      { name: 'evil.exe', data: Buffer.from('MZ') },
    ]);
    const plan = await planImportFromZip(exe, env);
    expect(!plan.ok && plan.errors.join()).toMatch(/白名单/);
  });

  it('清单字段校验：id 大写 / 未知状态 / 类名注入样式 → 拒绝', async () => {
    const bad = (manifest: unknown) =>
      planImportFromZip(
        buildZip([
          { name: 'pet.json', data: Buffer.from(JSON.stringify(manifest)) },
          { name: 'a.css', data: Buffer.from('.a{}') },
        ]),
        env,
      );
    expect((await bad({ ...GOOD_MANIFEST, id: 'PANDA' })).ok).toBe(false);
    expect((await bad({ ...GOOD_MANIFEST, animations: { meow: 'x' } })).ok).toBe(false);
    expect(
      (await bad({ ...GOOD_MANIFEST, bodyClass: 'a{color:red}.b' })).ok,
    ).toBe(false);
  });

  it('CSS 卫生：@import 与网络 url() → 拒绝', async () => {
    const importPlan = await planImportFromZip(
      goodPackZip({ 'styles/evil.css': '@import url("http://evil/x.css");' }),
      env,
    );
    expect(!importPlan.ok && importPlan.errors.join()).toMatch(/@import/);
    const urlPlan = await planImportFromZip(
      goodPackZip({ 'styles/evil.css': '.a{background:url(https://cdn/x.png)}' }),
      env,
    );
    expect(!urlPlan.ok && urlPlan.errors.join()).toMatch(/网络/);
  });
});

describe('commit / discard / remove', () => {
  it('plan → commit 入库，quarantine 清空，pets/<id> 可读', async () => {
    const plan = await planImportFromZip(goodPackZip(), env);
    if (!plan.ok) throw new Error('plan failed');
    expect((await commitImport(plan.token, { overwrite: false }, env)).ok).toBe(true);
    const packs = await listInstalledPacks(env);
    expect(packs.map((p) => p.id)).toEqual(['panda-01']);
    expect(packs[0]!.cssText).toContain('.pet-body-panda-01');
  });

  it('同 id 冲突：plan 标记 conflict，commit 需显式 overwrite', async () => {
    const first = await planImportFromZip(goodPackZip(), env);
    if (!first.ok) throw new Error('plan failed');
    await commitImport(first.token, { overwrite: false }, env);
    const second = await planImportFromZip(goodPackZip(), env);
    expect(second.ok && second.conflict).toBe(true);
    if (!second.ok) return;
    expect((await commitImport(second.token, { overwrite: false }, env)).ok).toBe(false);
    expect((await commitImport(second.token, { overwrite: true }, env)).ok).toBe(true);
  });

  it('未知 token commit 拒绝；discard 幂等删除隔离区', async () => {
    const plan = await planImportFromZip(goodPackZip(), env);
    if (!plan.ok) throw new Error('plan failed');
    expect((await commitImport('0'.repeat(35) + '-', { overwrite: false }, env)).ok).toBe(false);
    expect((await discardImport(plan.token, env)).ok).toBe(true);
    expect((await discardImport(plan.token, env)).ok).toBe(true);
    expect((await commitImport(plan.token, { overwrite: false }, env)).ok).toBe(false);
  });

  it('removePack：非法 id 与不存在均拒绝；正常删除后列表为空', async () => {
    const plan = await planImportFromZip(goodPackZip(), env);
    if (!plan.ok) throw new Error('plan failed');
    await commitImport(plan.token, { overwrite: false }, env);
    expect((await removePack('../pets', env)).ok).toBe(false);
    expect((await removePack('nope-1', env)).ok).toBe(false);
    expect((await removePack('panda-01', env)).ok).toBe(true);
    expect(await listInstalledPacks(env)).toEqual([]);
  });

  it('sweepStaleQuarantine：只清超时且非 active 的 token', async () => {
    const plan = await planImportFromZip(goodPackZip(), env);
    if (!plan.ok) throw new Error('plan failed');
    const dir = path.join(env.quarantineDir, plan.token);
    const stale = new Date(Date.now() - 48 * 3600_000);
    await utimes(dir, stale, stale);
    expect(await sweepStaleQuarantine(env, new Set([plan.token]))).toBe(0);
    expect(await sweepStaleQuarantine(env, new Set())).toBe(1);
    expect((await commitImport(plan.token, { overwrite: false }, env)).ok).toBe(false);
  });
});

describe('listInstalledPacks 资产内联与容错', () => {
  it('CSS url() 相对图片 → base64 data URL 内联', async () => {
    const zip = buildZip([
      { name: 'pet.json', data: Buffer.from(JSON.stringify(GOOD_MANIFEST)) },
      { name: 'styles/main.css', data: Buffer.from('.p{background:url(../assets/e.png)}') },
      { name: 'assets/e.png', data: TINY_PNG },
    ]);
    const plan = await planImportFromZip(zip, env);
    if (!plan.ok) throw new Error(JSON.stringify(plan));
    await commitImport(plan.token, { overwrite: false }, env);
    const [pack] = await listInstalledPacks(env);
    expect(pack!.cssText).toContain('url("data:image/png;base64,');
  });

  it('url() 越界 / 引用缺失 / 损坏包 → 跳过不影响其他包', async () => {
    const zip = buildZip([
      { name: 'pet.json', data: Buffer.from(JSON.stringify(GOOD_MANIFEST)) },
      { name: 'styles/main.css', data: Buffer.from('.p{background:url(../../secret.png)}') },
    ]);
    const plan = await planImportFromZip(zip, env);
    if (!plan.ok) throw new Error(JSON.stringify(plan));
    await commitImport(plan.token, { overwrite: false }, env);
    await mkdir(path.join(env.petsDir, 'broken'), { recursive: true });
    await writeFile(path.join(env.petsDir, 'broken', 'pet.json'), 'not json');
    expect(await listInstalledPacks(env)).toEqual([]);
  });
});
