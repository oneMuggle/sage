// electron/__tests__/logIpc.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logIpc-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR, SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL };
  process.env.SAGE_LOG_DIR = tmpDir;
  process.env.SAGE_LOG_LEVEL = 'debug';
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  for (const [k, v] of Object.entries(originalEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  vi.resetModules();
});

describe('logIpc', () => {
  it('writes log line with source=renderer when sage:log:write invoked', async () => {
    const handlers = new Map<string, (e: unknown, p: unknown) => Promise<unknown>>();
    const fakeIpcMain = {
      handle: (channel: string, handler: (e: unknown, p: unknown) => Promise<unknown>) => {
        handlers.set(channel, handler);
      },
    };
    const { registerLogIpc } = await import('../ipc/logIpc');
    registerLogIpc(fakeIpcMain as never);

    const handler = handlers.get('sage:log:write')!;
    const fakeEvt = { sender: { id: 123 } } as unknown;
    await handler(fakeEvt, { level: 'warn', msg: 'hello', meta: { x: 1 } });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);
    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    const obj = JSON.parse(lines[0]);
    expect(obj).toMatchObject({
      level: 'warn',
      source: 'renderer',
      msg: 'hello',
      meta: { x: 1 },
    });
  });

  it('rate limits: drops messages exceeding 100/sec from same sender', async () => {
    const handlers = new Map<string, (e: unknown, p: unknown) => Promise<unknown>>();
    const fakeIpcMain = {
      handle: (c: string, h: (e: unknown, p: unknown) => Promise<unknown>) => handlers.set(c, h),
    };
    const { registerLogIpc } = await import('../ipc/logIpc');
    registerLogIpc(fakeIpcMain as never);
    const handler = handlers.get('sage:log:write')!;
    const fakeEvt = { sender: { id: 999 } } as unknown;

    const promises: Promise<unknown>[] = [];
    for (let i = 0; i < 150; i++) {
      promises.push(handler(fakeEvt, { level: 'info', msg: `burst-${i}` }));
    }
    await Promise.all(promises);

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    if (!existsSync(file)) return;
    // Count only renderer-source lines (rate-limit warn is source='main').
    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    const rendererLines = lines
      .map((l) => JSON.parse(l) as { source?: string })
      .filter((o) => o.source === 'renderer');
    expect(rendererLines.length).toBeLessThanOrEqual(100);
  });
});
