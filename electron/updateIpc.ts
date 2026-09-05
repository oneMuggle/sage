import type { IpcMain, IpcMainInvokeEvent } from 'electron';
import type { CheckResult, UpdateManager } from './updateManager';
import type { UpdateStrategy } from './updateConfig';
import type { UpdateState } from './updateState';

export type UpdateStateChangedEvent = { state: UpdateState } | { percent: number };

export interface UpdateIpcRegistrationOptions {
  isTrustedRenderer: (sender: IpcMainInvokeEvent['sender']) => boolean;
  sendToRenderer?: (channel: 'update:state-changed', payload: UpdateStateChangedEvent) => void;
}

type InvokeHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
type UpdateIpcMain = Pick<IpcMain, 'handle' | 'on'> & {
  removeHandler?: (channel: string) => void;
  off?: (channel: string, listener: (...args: unknown[]) => void) => void;
};

const UPDATE_STRATEGIES: readonly UpdateStrategy[] = ['manual', 'auto-download', 'auto-install'];
const registrations = new WeakMap<object, () => void>();

export function registerUpdateIpc(
  ipcMain: UpdateIpcMain,
  updateManager: UpdateManager,
  options: UpdateIpcRegistrationOptions,
): () => void {
  registrations.get(ipcMain)?.();
  const channels = [
    'update:check',
    'update:download',
    'update:install',
    'update:rollback',
    'update:can-rollback',
    'update:set-strategy',
  ];
  const stateChangedListener = (...args: unknown[]) => {
    const event = args[0] as IpcMainInvokeEvent | undefined;
    if (!event || !options.isTrustedRenderer(event.sender)) return;
    const payload = args[1] as UpdateStateChangedEvent | undefined;
    if (payload !== undefined) options.sendToRenderer?.('update:state-changed', payload);
  };
  const requireTrusted = (event: IpcMainInvokeEvent): void => {
    if (!options.isTrustedRenderer(event.sender)) throw new Error('未授权的窗口请求');
  };
  const register = (channel: string, handler: InvokeHandler): void => {
    ipcMain.handle(channel, handler);
  };

  register('update:check', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.checkForUpdates() as Promise<CheckResult>;
  });
  register('update:download', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.downloadUpdate();
  });
  register('update:install', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.installUpdate();
  });
  register('update:rollback', async (event, payload?: unknown) => {
    requireTrusted(event as IpcMainInvokeEvent);
    const reason = payload === undefined ? 'manual' : payload;
    if (typeof reason !== 'string' || reason.trim().length === 0) {
      throw new Error('回滚原因必须是非空字符串');
    }
    return updateManager.rollback(reason);
  });
  register('update:can-rollback', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.canManualRollback();
  });
  register('update:set-strategy', async (event, payload?: unknown) => {
    requireTrusted(event as IpcMainInvokeEvent);
    if (typeof payload !== 'string' || !UPDATE_STRATEGIES.includes(payload as UpdateStrategy)) {
      throw new Error('无效的更新策略');
    }
    return updateManager.setStrategy(payload as UpdateStrategy);
  });

  ipcMain.on('update:state-changed', stateChangedListener);
  const stopProgress = updateManager.onDownloadProgress((percent) => {
    options.sendToRenderer?.('update:state-changed', { percent });
  });
  const cleanup = () => {
    for (const channel of channels) ipcMain.removeHandler?.(channel);
    ipcMain.off?.('update:state-changed', stateChangedListener);
    stopProgress();
    if (registrations.get(ipcMain) === cleanup) registrations.delete(ipcMain);
  };
  registrations.set(ipcMain, cleanup);
  return cleanup;
}
