// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { registerUpdateIpc } from '../updateIpc';

interface FakeIpcMain {
  handlers: Map<string, (...args: unknown[]) => unknown>;
  handle: (channel: string, handler: (...args: unknown[]) => unknown) => void;
  removeHandler: (channel: string) => void;
  on: (channel: string, listener: (...args: unknown[]) => void) => void;
  off: (channel: string, listener: (...args: unknown[]) => void) => void;
}

function createIpcMain(): FakeIpcMain {
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  return {
    handlers,
    handle: (channel, handler) => handlers.set(channel, handler),
    removeHandler: (channel) => handlers.delete(channel),
    on: () => {},
    off: () => {},
  };
}

function createManager() {
  return {
    checkForUpdates: vi.fn().mockResolvedValue({ updateAvailable: false }),
    downloadUpdate: vi.fn().mockResolvedValue(undefined),
    installUpdate: vi.fn().mockResolvedValue(undefined),
    rollback: vi.fn().mockResolvedValue(undefined),
    canManualRollback: vi.fn().mockResolvedValue({ allowed: true }),
    setStrategy: vi.fn().mockResolvedValue(undefined),
    getConfig: vi.fn().mockResolvedValue({
      updateStrategy: 'auto-download',
      channel: 'stable',
      rollbackWindowDays: 7,
      autoRollbackThreshold: 3,
      checkIntervalHours: 24,
      updateServerUrl: 'https://updates.sage.app',
      enableTelemetry: false,
      cacheRetentionDays: 30,
    }),
    setChannel: vi.fn().mockResolvedValue(undefined),
    onDownloadProgress: vi.fn().mockReturnValue(() => undefined),
    onStateChange: vi.fn().mockReturnValue(() => undefined),
  };
}

const trustedSender = { id: 1 };
const trustedEvent = { sender: trustedSender } as never;
const untrustedEvent = { sender: { id: 2 } } as never;

describe('registerUpdateIpc', () => {
  afterEach(() => vi.restoreAllMocks());

  it('registers all eight operations and forwards expected arguments', async () => {
    const ipc = createIpcMain();
    const manager = createManager();
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: (sender) => sender === trustedSender,
    });

    await ipc.handlers.get('update:check')?.(trustedEvent);
    await ipc.handlers.get('update:download')?.(trustedEvent);
    await ipc.handlers.get('update:install')?.(trustedEvent);
    await ipc.handlers.get('update:rollback')?.(trustedEvent, 'user requested');
    await ipc.handlers.get('update:can-rollback')?.(trustedEvent);
    await ipc.handlers.get('update:set-strategy')?.(trustedEvent, 'auto-install');
    await ipc.handlers.get('update:get-config')?.(trustedEvent);
    await ipc.handlers.get('update:set-channel')?.(trustedEvent, 'beta');

    expect(manager.checkForUpdates).toHaveBeenCalledOnce();
    expect(manager.downloadUpdate).toHaveBeenCalledOnce();
    expect(manager.installUpdate).toHaveBeenCalledOnce();
    expect(manager.rollback).toHaveBeenCalledWith('user requested');
    expect(manager.canManualRollback).toHaveBeenCalledOnce();
    expect(manager.setStrategy).toHaveBeenCalledWith('auto-install');
    expect(manager.getConfig).toHaveBeenCalledOnce();
    expect(manager.setChannel).toHaveBeenCalledWith('beta');
  });

  it('rejects untrusted senders before calling the manager', async () => {
    const ipc = createIpcMain();
    const manager = createManager();
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: (sender) => sender === trustedSender,
    });

    await expect(ipc.handlers.get('update:check')?.(untrustedEvent)).rejects.toThrow(
      '未授权的窗口请求',
    );
    await expect(
      ipc.handlers.get('update:set-strategy')?.(untrustedEvent, 'manual'),
    ).rejects.toThrow('未授权的窗口请求');
    await expect(ipc.handlers.get('update:get-config')?.(untrustedEvent)).rejects.toThrow(
      '未授权的窗口请求',
    );
    await expect(ipc.handlers.get('update:set-channel')?.(untrustedEvent, 'beta')).rejects.toThrow(
      '未授权的窗口请求',
    );
    expect(manager.checkForUpdates).not.toHaveBeenCalled();
    expect(manager.setStrategy).not.toHaveBeenCalled();
  });

  it('validates strategy and rollback reason, with manual as the default reason', async () => {
    const ipc = createIpcMain();
    const manager = createManager();
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: () => true,
    });

    await ipc.handlers.get('update:rollback')?.(trustedEvent);
    expect(manager.rollback).toHaveBeenCalledWith('manual');
    await expect(ipc.handlers.get('update:rollback')?.(trustedEvent, '   ')).rejects.toThrow(
      '回滚原因必须是非空字符串',
    );
    // Non-string payloads are coerced via String(); numeric 123 → "123" (valid)
    await ipc.handlers.get('update:rollback')?.(trustedEvent, 123);
    expect(manager.rollback).toHaveBeenLastCalledWith('123');
    await expect(ipc.handlers.get('update:set-strategy')?.(trustedEvent, 'bad')).rejects.toThrow(
      '无效的更新策略',
    );
    await expect(ipc.handlers.get('update:set-channel')?.(trustedEvent, 'nightly')).rejects.toThrow(
      '无效的更新渠道',
    );
  });

  it('trims rollback reason uniformly before passing to manager', async () => {
    const ipc = createIpcMain();
    const manager = createManager();
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: () => true,
    });

    await ipc.handlers.get('update:rollback')?.(trustedEvent, '  user-requested  ');
    expect(manager.rollback).toHaveBeenCalledWith('user-requested');
  });

  it('relays download progress via sendToRenderer with discriminated tag', () => {
    const ipc = createIpcMain();
    const manager = createManager();
    const sendToRenderer = vi.fn();
    const cleanup = registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: () => true,
      sendToRenderer,
    });

    // Simulate download progress from the manager
    const progressCallback = manager.onDownloadProgress.mock.calls[0]?.[0] as (
      percent: number,
    ) => void;
    progressCallback(42);
    expect(sendToRenderer).toHaveBeenCalledWith('update:state-changed', {
      type: 'progress',
      percent: 42,
    });

    // After cleanup, progress callback should have been unsubscribed
    cleanup();
    expect(ipc.handlers.size).toBe(0);
  });

  it('does not register an ipcMain.on listener for state-changed', () => {
    const ipc = createIpcMain();
    const onSpy = vi.spyOn(ipc, 'on');
    const manager = createManager();
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: () => true,
    });
    // No ipcMain.on('update:state-changed', ...) — relay is via sendToRenderer
    expect(onSpy).not.toHaveBeenCalled();
  });

  it('propagates manager errors', async () => {
    const ipc = createIpcMain();
    const manager = createManager();
    manager.downloadUpdate.mockRejectedValue(new Error('download failed'));
    registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: () => true,
    });

    await expect(ipc.handlers.get('update:download')?.(trustedEvent)).rejects.toThrow(
      'download failed',
    );
  });
});

describe('preload update bridge', () => {
  it('uses update channels and removes listeners with off', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const on = vi.fn();
    const off = vi.fn();
    vi.resetModules();
    vi.doMock('electron', () => ({
      contextBridge: { exposeInMainWorld: vi.fn() },
      ipcRenderer: { invoke, on, off },
    }));
    await import('../preload');
    const exposed = vi.mocked((await import('electron')).contextBridge.exposeInMainWorld).mock
      .calls[0]?.[1] as { updates: Record<string, (...args: unknown[]) => unknown> };

    await exposed.updates.check();
    await exposed.updates.download();
    await exposed.updates.install();
    await exposed.updates.rollback('manual');
    await exposed.updates.canRollback();
    await exposed.updates.setStrategy('manual');
    await exposed.updates.getConfig();
    await exposed.updates.setChannel('beta');
    expect(invoke.mock.calls.map(([channel]) => channel)).toEqual([
      'update:check',
      'update:download',
      'update:install',
      'update:rollback',
      'update:can-rollback',
      'update:set-strategy',
      'update:get-config',
      'update:set-channel',
    ]);

    const handler = vi.fn();
    const unlisten = exposed.updates.onStateChanged(handler) as () => void;
    expect(on).toHaveBeenCalledWith('update:state-changed', expect.any(Function));
    unlisten();
    expect(off).toHaveBeenCalledWith('update:state-changed', on.mock.calls[0][1]);
  });
});
