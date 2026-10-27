/**
 * R111 usePluginNames:模块级缓存的生命周期名单读取。
 * 用例顺序即契约的一部分(同文件共享模块缓存):禁用不取 →
 * 失败不毒化 → 并发合并一次 → TTL 内复用。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePluginNames } from '../usePluginNames';

const listMock = vi.fn();
vi.mock('../../../api/pluginClient', () => ({
  pluginClient: {
    list: (...a: unknown[]) => listMock(...a),
  },
}));

beforeEach(() => {
  listMock.mockReset();
});

describe('usePluginNames', () => {
  it('does not fetch while disabled', () => {
    const { result } = renderHook(() => usePluginNames(false));
    expect(result.current).toBeNull();
    expect(listMock).not.toHaveBeenCalled();
  });

  it('returns null when the list cannot be loaded (and does not poison the cache)', async () => {
    listMock.mockRejectedValue(new Error('backend down'));
    const { result } = renderHook(() => usePluginNames(true));
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));
    expect(result.current).toBeNull();
  });

  it('coalesces concurrent mounts into one list call', async () => {
    let resolveList: (records: { name: string }[]) => void = () => undefined;
    listMock.mockImplementation(
      () =>
        new Promise<{ name: string }[]>((resolve) => {
          resolveList = resolve;
        }),
    );
    const first = renderHook(() => usePluginNames(true));
    const second = renderHook(() => usePluginNames(true));
    expect(listMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveList([{ name: 'demo' }]);
    });
    await waitFor(() => expect(first.result.current).toEqual(['demo']));
    expect(second.result.current).toEqual(['demo']);
  });

  it('serves later mounts from the TTL cache without refetching', () => {
    const { result } = renderHook(() => usePluginNames(true));
    expect(result.current).toEqual(['demo']);
    expect(listMock).not.toHaveBeenCalled();
  });
});
