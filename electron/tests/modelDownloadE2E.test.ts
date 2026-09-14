/**
 * P10 (2026-09-14): embedder 下载端到端集成测试 —— 真实清单对 hf-mirror
 * 走完整链路：download → 逐文件下载 + SHA-256 校验 → 平铺落盘 → 进度事件。
 *
 * 运行条件：SAGE_NIGHTLY=1（由 .github/workflows/e2e-nightly.yml 注入）。
 * 平时跳过 —— PR 门禁零真实网络依赖；nightly 验证清单 URL/校验和未腐化。
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const sendMock = vi.fn();
const handlers = new Map<string, unknown>();

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn((channel: string, fn: unknown) => {
      handlers.set(channel, fn);
    }),
  },
}));

import { EMBEDDER_MODEL_MANIFEST, registerModelDownloadIpc } from '../modelDownloadIpc';

const NIGHTLY = process.env.SAGE_NIGHTLY === '1';
const d = NIGHTLY ? describe : describe.skip;

describe('embedder download E2E (nightly, real network)', () => {
  let modelsDir: string;

  const register = (): void => {
    handlers.clear();
    sendMock.mockClear();
    registerModelDownloadIpc(
      { handle: (c: string, fn: unknown) => handlers.set(c, fn) } as never,
      {
        modelsBaseDir: () => modelsDir,
        getWindow: () =>
          ({
            isDestroyed: () => false,
            webContents: { send: sendMock },
          }) as never,
      },
    );
  };

  beforeEach(() => {
    modelsDir = mkdtempSync(join(tmpdir(), 'sage-embedder-e2e-'));
    sendMock.mockClear();
    handlers.clear();
    register();
  });

  afterEach(() => {
    rmSync(modelsDir, { recursive: true, force: true });
  });

  it('真实清单完整链路：下载 → sha256 校验 → 平铺落盘 → 进度事件', async () => {
    const download = handlers.get('models:embedder:download') as (
      evt: unknown,
      p: unknown,
    ) => Promise<{ ok: boolean; totalBytes?: number; error?: string }>;

    // 无参调用 → 内置清单（hf-mirror + 两个文件 + sha256）
    const result = await download(null, {});
    expect(result).toMatchObject({ ok: true });
    expect((result.totalBytes ?? 0)).toBeGreaterThan(90_000_000);

    // 平铺落盘（basename）且字节级与清单一致
    const modelDir = join(modelsDir, EMBEDDER_MODEL_MANIFEST.dirName);
    for (const f of EMBEDDER_MODEL_MANIFEST.files) {
      const flat = f.name.split('/').pop()!;
      const p = join(modelDir, flat);
      expect(existsSync(p)).toBe(true);
      const hash = createHash('sha256').update(readFileSync(p)).digest('hex');
      expect(hash).toBe(f.sha256);
    }

    // 进度事件：全部走 sage:event: 前缀；序列含 start / 逐文件 done / complete
    const calls = sendMock.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    for (const [channel] of calls) {
      expect(channel).toBe('sage:event:models:embedder:progress');
    }
    const stages = calls.map(([, p]) => (p as { stage: string }).stage);
    expect(stages[0]).toBe('start');
    expect(stages).toContain('complete');
    const doneFiles = calls
      .filter(([, p]) => (p as { stage: string }).stage === 'done')
      .map(([, p]) => (p as { file: string }).file.split('/').pop());
    expect(doneFiles.sort()).toEqual(
      EMBEDDER_MODEL_MANIFEST.files.map((f) => f.name.split('/').pop()).sort(),
    );
  }, 600_000);
});
