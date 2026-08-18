/**
 * PR-B RED test: desktopInvoke ECONNREFUSED 友好翻译。
 *
 * 验证当 main 进程把后端 ECONNREFUSED / fetch failed 通过 IPC 抛回时,
 * renderer 唯一漏斗处（src/shared/api/desktopInvoke.ts:invoke）应翻译为
 * 中文友好提示「后端服务未启动或已断开」。
 *
 * 注意：desktopInvoke.ts 不直接 import 'electron'，而是委托 window.electronAPI.invoke
 * （preload bridge 通过 contextBridge 注入）。所以 mock 必须打到 window.electronAPI
 * 而不是 electron.ipcRenderer —— 否则 mock 不会拦截到 invoke 路径。
 *
 * Task 8 才会实现实际的翻译逻辑；当前 invoke 在 catch 块里直接 `throw err`，所以
 * 三个测试都应 RED（断言不匹配原 error.message）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.fn();
(window as unknown as Record<string, unknown>).electronAPI = { invoke: invokeMock };

import { invoke } from './desktopInvoke';

describe('desktopInvoke ECONNREFUSED translation (PR-B)', () => {
  beforeEach(() => {
    invokeMock.mockReset();
  });

  afterEach(() => {
    invokeMock.mockReset();
  });

  it('translates ECONNREFUSED to friendly Chinese error', async () => {
    invokeMock.mockRejectedValueOnce(
      new Error(
        'request to http://127.0.0.1:8765/api/v1/settings failed, ' +
          'reason: connect ECONNREFUSED 127.0.0.1:8765',
      ),
    );
    await expect(invoke('get_settings')).rejects.toThrow(/后端服务未启动或已断开/);
  });

  it('translates fetch failed (Node 18+) to friendly Chinese error', async () => {
    invokeMock.mockRejectedValueOnce(new TypeError('fetch failed'));
    await expect(invoke('get_settings')).rejects.toThrow(/后端服务未启动或已断开/);
  });

  it('passes through non-ECONNREFUSED errors unchanged', async () => {
    invokeMock.mockRejectedValueOnce(
      new Error('Backend validation failed: field required'),
    );
    await expect(invoke('set_settings')).rejects.toThrow(/validation/);
  });
});