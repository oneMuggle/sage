/**
 * backendReadySignal 单测——订阅注册 / 事件广播 / 退订 / tick 自增 / 无 electronAPI 降级。
 *
 * 模块内部是单例（installed + handlers 集合），因此每个用例前 resetModules，
 * 保证用例之间互不污染。
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type ListenHandler = (payload: unknown) => void;

interface StubApi {
  listen: ReturnType<typeof vi.fn>;
  handlers: Map<string, ListenHandler>;
  emit: (event: string) => void;
}

function stubElectronApi(): StubApi {
  const handlers = new Map<string, ListenHandler>();
  const listen = vi.fn((event: string, handler: ListenHandler) => {
    handlers.set(event, handler);
    return Promise.resolve(() => undefined);
  });
  (window as unknown as { electronAPI: unknown }).electronAPI = { listen };
  return {
    listen,
    handlers,
    emit: (event: string) => handlers.get(event)?.(undefined),
  };
}

beforeEach(() => {
  vi.resetModules();
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

describe('onBackendReady', () => {
  it('backend:ready 触发时回调已注册的 handler', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');
    const handler = vi.fn();

    mod.onBackendReady(handler);
    stub.emit('backend:ready');

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('backend:reconnected 同样触发回调', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');
    const handler = vi.fn();

    mod.onBackendReady(handler);
    stub.emit('backend:reconnected');

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('退订后不再收到回调', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');
    const handler = vi.fn();

    const unsubscribe = mod.onBackendReady(handler);
    unsubscribe();
    stub.emit('backend:ready');

    expect(handler).not.toHaveBeenCalled();
  });

  it('多个订阅者共享同一份 IPC 订阅（单例）', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');
    const a = vi.fn();
    const b = vi.fn();

    mod.onBackendReady(a);
    mod.onBackendReady(b);
    stub.emit('backend:ready');

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    const readyCalls = stub.listen.mock.calls.filter((c) => c[0] === 'backend:ready');
    expect(readyCalls).toHaveLength(1);
  });

  it('一个订阅者抛错不影响其他订阅者', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const good = vi.fn();

    mod.onBackendReady(() => {
      throw new Error('boom');
    });
    mod.onBackendReady(good);
    stub.emit('backend:ready');

    expect(good).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it('缺少 electronAPI 时静默降级，不抛错', async () => {
    const mod = await import('../backendReadySignal');
    expect(() => mod.onBackendReady(vi.fn())).not.toThrow();
  });
});

describe('useBackendReadyTick', () => {
  it('初始为 0，收到 backend:ready 后自增', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');

    const { result } = renderHook(() => mod.useBackendReadyTick());
    expect(result.current).toBe(0);

    await act(async () => {
      stub.emit('backend:ready');
    });
    expect(result.current).toBe(1);

    await act(async () => {
      stub.emit('backend:ready');
    });
    expect(result.current).toBe(2);
  });

  it('卸载后不再自增', async () => {
    const stub = stubElectronApi();
    const mod = await import('../backendReadySignal');

    const { result, unmount } = renderHook(() => mod.useBackendReadyTick());
    unmount();
    await act(async () => {
      stub.emit('backend:ready');
    });
    expect(result.current).toBe(0);
  });
});
