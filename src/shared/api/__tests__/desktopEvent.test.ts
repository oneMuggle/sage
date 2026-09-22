/**
 * r97: desktopEvent 单测——listen 垫片的 payload 包装、streamId 转发与无 preload 报错。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { listen } from '../desktopEvent';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('desktopEvent.listen', () => {
  it('把 electronAPI 的 (payload) 还原为 Tauri 风格 ({ payload })', async () => {
    let captured: ((payload: unknown) => void) | null = null;
    const unlisten = vi.fn();
    const apiListen = vi.fn((_event: string, fn: (payload: unknown) => void) => {
      captured = fn;
      return unlisten;
    });
    vi.stubGlobal('window', { electronAPI: { listen: apiListen } });

    const seen: Array<{ payload: string }> = [];
    const stop = await listen<string>('evt', (e) => seen.push(e));

    captured?.('hello');
    expect(seen).toEqual([{ payload: 'hello' }]);
    expect(stop).toBe(unlisten);
    expect(apiListen).toHaveBeenCalledWith('evt', expect.any(Function), undefined);
  });

  it('options.streamId 透传给 electronAPI.listen 第三参', async () => {
    const apiListen = vi.fn().mockReturnValue(vi.fn());
    vi.stubGlobal('window', { electronAPI: { listen: apiListen } });

    await listen('orch-events-run-1', () => {}, { streamId: 'sid-9' });
    expect(apiListen).toHaveBeenCalledWith(
      'orch-events-run-1',
      expect.any(Function),
      { streamId: 'sid-9' },
    );
  });

  it('无 electronAPI（纯浏览器）抛可读错误且不触发 handler', async () => {
    vi.stubGlobal('window', {});
    await expect(listen('evt', () => {})).rejects.toThrow('electronAPI not available');
  });
});
