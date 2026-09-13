/**
 * P5: models:embedder:download 的进度事件通道断言。
 *
 * 进度事件必须带 `sage:event:` 前缀发送（preload listen shim 只在
 * `sage:event:<event>` 上注册）——与 backend:* 通道修复（#733）同族。
 * 网络层不真实请求：baseUrl 指向未监听端口，start 事件先行发出、
 * fetch 失败后发出 error 事件，两条都应走前缀通道。
 * 注意：ipcMain.handle 的 handler 签名是 (evt, payload)，直接调用时
 * 第一个参数传 null。
 */
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const sendMock = vi.fn();
const handlers = new Map<string, unknown>();

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn((channel: string, fn: unknown) => {
      handlers.set(channel, fn);
    }),
  },
}));

import { registerModelDownloadIpc } from '../modelDownloadIpc';

function invokeDownload(payload: unknown): Promise<unknown> {
  const fn = handlers.get('models:embedder:download') as (
    evt: unknown,
    p: unknown,
  ) => Promise<unknown>;
  return fn(null, payload);
}

describe('modelDownloadIpc progress channel (P5)', () => {
  beforeEach(() => {
    sendMock.mockClear();
    handlers.clear();
    registerModelDownloadIpc(
      { handle: (c: string, f: unknown) => handlers.set(c, f) } as never,
      {
        modelsBaseDir: () => join(tmpdir(), 'sage-test-models'),
        getWindow: () =>
          ({
            isDestroyed: () => false,
            webContents: { send: sendMock },
          }) as never,
      },
    );
  });

  it('进度事件走 sage:event: 前缀通道（start 与 error 两阶段）', async () => {
    const result = await invokeDownload({
      baseUrl: 'http://127.0.0.1:9/models',
      dirName: 'bge-small-zh-v1.5',
      files: [{ name: 'model.onnx', sha256: '0'.repeat(64) }],
    });

    const channels = sendMock.mock.calls.map(([channel]) => channel);
    expect(channels).toContain('sage:event:models:embedder:progress');
    expect(channels).not.toContain('models:embedder:progress');
    // 失败路径返回 ok:false（fetch 被拒）
    expect(result).toMatchObject({ ok: false });
  });

  it('重复下载同一 dirName 被拒绝（already-running）', async () => {
    // 首次调用挂起在 fetch 上（不 await）；再次发起同 dirName 应立刻拒绝
    const pending = invokeDownload({
      baseUrl: 'http://127.0.0.1:9/models',
      dirName: 'bge-dup',
      files: [{ name: 'model.onnx', sha256: '0'.repeat(64) }],
    });
    await expect(
      invokeDownload({
        baseUrl: 'http://127.0.0.1:9/models',
        dirName: 'bge-dup',
        files: [{ name: 'model.onnx', sha256: '0'.repeat(64) }],
      }),
    ).resolves.toMatchObject({ ok: false, error: 'already-running' });
    await pending;
  });
});
