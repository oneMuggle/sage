import type { IpcMain, IpcMainInvokeEvent } from 'electron';
import type { UpdateManager } from './updateManager';
import type { UpdateChannel, UpdateStrategy } from './updateConfig';
import type { UpdateState } from './updateState';

export type UpdateStateChangedEvent =
  | { type: 'state'; state: UpdateState }
  | { type: 'progress'; percent: number };

export interface UpdateIpcRegistrationOptions {
  isTrustedRenderer: (sender: IpcMainInvokeEvent['sender']) => boolean;
  sendToRenderer?: (channel: 'update:state-changed', payload: UpdateStateChangedEvent) => void;
}

type InvokeHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown;
type UpdateIpcMain = Pick<IpcMain, 'handle' | 'removeHandler'>;

const UPDATE_STRATEGIES: readonly UpdateStrategy[] = ['manual', 'auto-download', 'auto-install'];
const UPDATE_CHANNELS: readonly UpdateChannel[] = ['stable', 'beta', 'alpha'];
let currentCleanup: (() => void) | null = null;

export function registerUpdateIpc(
  ipcMain: UpdateIpcMain,
  updateManager: UpdateManager,
  options: UpdateIpcRegistrationOptions,
): () => void {
  currentCleanup?.();
  const channels = [
    'update:check',
    'update:download',
    'update:install',
    'update:rollback',
    'update:can-rollback',
    'update:set-strategy',
    'update:get-config',
    'update:set-channel',
  ];
  const requireTrusted = (event: IpcMainInvokeEvent): void => {
    if (!options.isTrustedRenderer(event.sender)) throw new Error('未授权的窗口请求');
  };
  const register = (channel: string, handler: InvokeHandler): void => {
    ipcMain.handle(channel, handler);
  };

  register('update:check', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.checkForUpdates();
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
    const reason = (payload === undefined ? 'manual' : String(payload)).trim();
    if (reason.length === 0) {
      throw new Error('回滚原因必须是非空字符串');
    }
    const checked = await updateManager.canManualRollback();
    if (!checked.allowed) {
      throw new Error(checked.reason ?? '手动回滚不可用');
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
  register('update:get-config', async (event) => {
    requireTrusted(event as IpcMainInvokeEvent);
    return updateManager.getConfig();
  });
  register('update:set-channel', async (event, payload?: unknown) => {
    requireTrusted(event as IpcMainInvokeEvent);
    if (typeof payload !== 'string' || !UPDATE_CHANNELS.includes(payload as UpdateChannel)) {
      throw new Error('无效的更新渠道');
    }
    return updateManager.setChannel(payload as UpdateChannel);
  });

  // State events are relayed to the renderer via the sendToRenderer callback
  // (main.ts passes mainWindow?.webContents.send directly). No ipcMain.on relay
  // is needed — sendToRenderer already targets the trusted mainWindow instance.
  const stopProgress = updateManager.onDownloadProgress((percent) => {
    options.sendToRenderer?.('update:state-changed', { type: 'progress', percent });
  });
  const stopStateRelay = updateManager.onStateChange((state) => {
    options.sendToRenderer?.('update:state-changed', { type: 'state', state });
  });
  const cleanup = () => {
    for (const channel of channels) ipcMain.removeHandler(channel);
    stopProgress();
    stopStateRelay();
    if (currentCleanup === cleanup) currentCleanup = null;
  };
  currentCleanup = cleanup;
  return cleanup;
}
