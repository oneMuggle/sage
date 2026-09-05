import { afterEach, describe, expect, it, vi } from 'vitest';
import { registerUpdateIpc } from '../updateIpc';

interface FakeIpcMain {
  handlers: Map<string, (...args: unknown[]) => unknown>;
  listeners: Map<string, (...args: unknown[]) => void>;
  handle: (channel: string, handler: (...args: unknown[]) => unknown) => void;
  on: (channel: string, listener: (...args: unknown[]) => void) => void;
  off: (channel: string, listener: (...args: unknown[]) => void) => void;
  removeHandler: (channel: string) => void;
}

function createIpcMain(): FakeIpcMain {
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  const listeners = new Map<string, (...args: unknown[]) => void>();
  return {
    handlers,
    listeners,
    handle: (channel, handler) => handlers.set(channel, handler),
    on: (channel, listener) => listeners.set(channel, listener),
    off: (channel, listener) => {
      if (listeners.get(channel) === listener) listeners.delete(channel);
    },
    removeHandler: (channel) => handlers.delete(channel),
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
    onDownloadProgress: vi.fn().mockReturnValue(() => undefined),
  };
}

const trustedSender = { id: 1 };
const trustedEvent = { sender: trustedSender } as never;
const untrustedEvent = { sender: { id: 2 } } as never;

describe('registerUpdateIpc', () => {
  afterEach(() => vi.restoreAllMocks());

  it('registers all six operations and forwards expected arguments', async () => {
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

    expect(manager.checkForUpdates).toHaveBeenCalledOnce();
    expect(manager.downloadUpdate).toHaveBeenCalledOnce();
    expect(manager.installUpdate).toHaveBeenCalledOnce();
    expect(manager.rollback).toHaveBeenCalledWith('user requested');
    expect(manager.canManualRollback).toHaveBeenCalledOnce();
    expect(manager.setStrategy).toHaveBeenCalledWith('auto-install');
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
    await expect(ipc.handlers.get('update:set-strategy')?.(untrustedEvent, 'manual')).rejects.toThrow(
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
    await expect(ipc.handlers.get('update:rollback')?.(trustedEvent, 123)).rejects.toThrow();
    await expect(ipc.handlers.get('update:set-strategy')?.(trustedEvent, 'bad')).rejects.toThrow(
      '无效的更新策略',
    );
  });

  it('forwards state events and stops forwarding after cleanup', () => {
    const ipc = createIpcMain();
    const manager = createManager();
    const sendToRenderer = vi.fn();
    const cleanup = registerUpdateIpc(ipc as never, manager as never, {
      isTrustedRenderer: (sender) => sender === trustedSender,
      sendToRenderer,
    });

    ipc.listeners.get('update:state-changed')?.(
      { sender: trustedSender },
      { state: { currentVersion: '1.0.0' } },
    );
    expect(sendToRenderer).toHaveBeenCalledWith('update:state-changed', {
      state: { currentVersion: '1.0.0' },
    });
    cleanup();
    expect(ipc.handlers).toHaveLength(0);
    expect(ipc.listeners).toHaveLength(0);
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
    expect(invoke.mock.calls.map(([channel]) => channel)).toEqual([
      'update:check',
      'update:download',
      'update:install',
      'update:rollback',
      'update:can-rollback',
      'update:set-strategy',
    ]);

    const handler = vi.fn();
    const unlisten = exposed.updates.onStateChanged(handler) as () => void;
    expect(on).toHaveBeenCalledWith('update:state-changed', expect.any(Function));
    unlisten();
    expect(off).toHaveBeenCalledWith('update:state-changed', on.mock.calls[0][1]);
  });
});
