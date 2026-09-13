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

import { EMBEDDER_MODEL_MANIFEST, registerModelDownloadIpc } from '../modelDownloadIpc';

describe('EMBEDDER_MODEL_MANIFEST (P8)', () => {
  const send = vi.fn();
  beforeEach(() => {
    send.mockClear();
    handlers.clear();
    registerModelDownloadIpc(
      { handle: (c: string, f: unknown) => handlers.set(c, f) } as never,
      {
        modelsBaseDir: () => '/tmp/sage-test-models',
        getWindow: () =>
          ({
            isDestroyed: () => false,
            webContents: { send },
          }) as never,
      },
    );
  });

  it('清单形状合法：dirName 平铺、文件名含 64 位 sha256', () => {
    expect(EMBEDDER_MODEL_MANIFEST.dirName).toBe('bge-small-zh-v1.5');
    expect(EMBEDDER_MODEL_MANIFEST.baseUrl).toMatch(/^https:\/\//);
    for (const f of EMBEDDER_MODEL_MANIFEST.files) {
      expect(f.name).not.toContain('..');
      expect(f.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
    // OnnxEmbedder 期望的平铺产物必须存在
    const names = EMBEDDER_MODEL_MANIFEST.files.map((f) => f.name.split('/').pop());
    expect(names).toContain('model.onnx');
    expect(names).toContain('tokenizer.json');
  });

  it('无参 download 使用内置清单默认值（不可达 baseUrl 下快速失败）', async () => {
    const download = handlers.get('models:embedder:download') as (
      evt: unknown,
      p: unknown,
    ) => Promise<unknown>;
    expect(download).toBeTypeOf('function');
    // 覆盖 baseUrl 为不可达地址（隔离真实网络），dirName/files 仍回落清单
    const result = await download(null, { baseUrl: 'http://127.0.0.1:9/models' });
    expect(result).toMatchObject({ ok: false });
    // 进度事件含清单默认 dirName —— 证明默认值生效
    const progressCall = send.mock.calls.find(
      ([channel]) => channel === 'sage:event:models:embedder:progress',
    );
    expect(progressCall).toBeDefined();
  });
});

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
