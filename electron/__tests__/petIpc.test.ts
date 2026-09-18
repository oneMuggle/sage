/**
 * P2 petIpc 接线测试：dialog → plan → commit/discard/remove 通道贯通，
 * 环境路径经 userDataPaths 桩注入临时目录。
 */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { deflateRawSync } from 'node:zlib';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { crc32 } from '../zipRead';

const mocks = vi.hoisted(() => ({
  dialog: { showOpenDialog: vi.fn() },
  tmpRoot: { value: '' },
}));

vi.mock('electron', () => ({
  dialog: mocks.dialog,
  BrowserWindow: { getFocusedWindow: vi.fn(() => null) },
}));

vi.mock('../userDataPaths', () => ({
  resolveSageUserDataDir: () => mocks.tmpRoot.value,
}));

const handlers = new Map<string, (...args: unknown[]) => unknown>();
function fakeRegister(channel: string, handler: (...args: unknown[]) => unknown): void {
  handlers.set(channel, handler);
}

async function writeGoodZip(): Promise<string> {
  const { writeFile } = await import('node:fs/promises');
  const manifest = JSON.stringify({
    id: 'ipc-panda',
    name: 'IPC 熊猫',
    bodyClass: 'pet-body-ipc-panda',
    animations: { idle: 'anim-idle' },
  });
  const css = '.pet-body-ipc-panda{width:10px}';
  const entries = [
    { name: 'pet.json', data: Buffer.from(manifest) },
    { name: 'main.css', data: Buffer.from(css) },
  ].map((e) => ({ ...e, comp: deflateRawSync(e.data) }));
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const e of entries) {
    const name = Buffer.from(e.name, 'utf8');
    const local = Buffer.alloc(30 + name.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(19752, 12);
    local.writeUInt32LE(crc32(e.data), 14);
    local.writeUInt32LE(e.comp.length, 18);
    local.writeUInt32LE(e.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    name.copy(local, 30);
    locals.push(local, e.comp);
    const central = Buffer.alloc(46 + name.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(8, 10);
    central.writeUInt32LE(crc32(e.data), 16);
    central.writeUInt32LE(e.comp.length, 20);
    central.writeUInt32LE(e.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    name.copy(central, 46);
    centrals.push(central);
    offset += local.length + e.comp.length;
  }
  const cd = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cd.length, 12);
  eocd.writeUInt32LE(offset, 16);
  const file = path.join(mocks.tmpRoot.value, 'pack.zip');
  await writeFile(file, Buffer.concat([...locals, cd, eocd]));
  return file;
}

describe('petIpc 通道', () => {
  beforeEach(async () => {
    handlers.clear();
    mocks.tmpRoot.value = await Promise.resolve(
      mkdtempSync(path.join(tmpdir(), 'pet-ipc-')),
    );
    mocks.dialog.showOpenDialog.mockReset();
    const { registerPetIpc, __resetPendingTokensForTests } = await import('../petIpc');
    __resetPendingTokensForTests();
    registerPetIpc(fakeRegister);
  });

  it('dialog 取消 → plan 返回 null', async () => {
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });
    expect(await handlers.get('pet:import-plan')!({})).toBeNull();
  });

  it('plan → commit → list → remove 全链路', async () => {
    const zip = await writeGoodZip();
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: false, filePaths: [zip] });
    const plan = (await handlers.get('pet:import-plan')!({})) as {
      ok: boolean;
      token: string;
      manifest: { id: string };
    };
    expect(plan.ok).toBe(true);
    const commit = (await handlers.get('pet:import-commit')!({}, { token: plan.token, overwrite: false })) as {
      ok: boolean;
    };
    expect(commit.ok).toBe(true);
    const packs = (await handlers.get('pet:list-imports')!({})) as Array<{ id: string; cssText: string }>;
    expect(packs.map((p) => p.id)).toEqual(['ipc-panda']);
    expect(packs[0]!.cssText).toContain('pet-body-ipc-panda');
    const removed = (await handlers.get('pet:remove-pack')!({}, { id: 'ipc-panda' })) as { ok: boolean };
    expect(removed.ok).toBe(true);
    expect((await handlers.get('pet:list-imports')!({})) as unknown[]).toEqual([]);
  });

  it('discard 后 commit 失败', async () => {
    const zip = await writeGoodZip();
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: false, filePaths: [zip] });
    const plan = (await handlers.get('pet:import-plan')!({})) as { token: string };
    const discarded = (await handlers.get('pet:import-discard')!({}, { token: plan.token })) as {
      ok: boolean;
    };
    expect(discarded.ok).toBe(true);
    const commit = (await handlers.get('pet:import-commit')!({}, { token: plan.token, overwrite: false })) as {
      ok: boolean;
    };
    expect(commit.ok).toBe(false);
  });
});
