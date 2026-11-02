/**
 * Whitelisted pet IPC.
 *
 * The pet window is deliberately NOT a trusted renderer for `sage:invoke` /
 * `sage:listen`; these channels are the only bridge it gets. Every handler
 * checks the sender window.
 */

import { dialog, ipcMain, type IpcMainEvent, type IpcMainInvokeEvent } from 'electron';

import type { PetController } from './controller';

const UNAUTHORIZED = '未授权的宠物窗口请求';

/** Every channel registered below; kept in sync so dispose can unregister. */
const PET_INVOKE_CHANNELS = [
  'pet:get-config',
  'pet:set-config',
  'pet:get-state',
  'pet:list-packs',
  'pet:api-info',
  'pet:import-pack',
  'pet:export-pack',
  'pet:delete-pack',
] as const;

const PET_EVENT_CHANNELS = [
  'pet:ready',
  'pet:open-session',
  'pet:open-settings',
  'pet:show-menu',
  'pet:drag-start',
  'pet:drag-move',
  'pet:drag-end',
  'pet:reset-position',
  'pet:set-panel',
  'pet:toggle-panel',
  'pet:pat',
  'pet:report-tasks',
  'pet:hide',
] as const;

function sessionIdOf(payload: unknown): string | null {
  if (typeof payload === 'string') return payload;
  if (payload && typeof payload === 'object' && 'sessionId' in payload) {
    const value = (payload as { sessionId?: unknown }).sessionId;
    return typeof value === 'string' && value ? value : null;
  }
  return null;
}

function packIdOf(payload: unknown): string | null {
  if (typeof payload === 'string') return payload;
  if (payload && typeof payload === 'object' && 'id' in payload) {
    const value = (payload as { id?: unknown }).id;
    return typeof value === 'string' && value ? value : null;
  }
  return null;
}

export function registerPetIpc(controller: PetController): void {
  const isPet = (evt: IpcMainEvent | IpcMainInvokeEvent): boolean =>
    controller.isPetSender(evt.sender);
  const isAllowed = (evt: IpcMainEvent | IpcMainInvokeEvent): boolean =>
    isPet(evt) || controller.isMainSender(evt.sender);

  ipcMain.handle('pet:get-config', (evt) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    return controller.getConfigForSender(evt.sender);
  });

  ipcMain.handle('pet:set-config', (evt, patch: unknown) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    // The local status API is a security-sensitive global switch: only the
    // settings window may toggle it (pet windows keep the narrow bridge).
    if (
      patch &&
      typeof patch === 'object' &&
      Object.prototype.hasOwnProperty.call(patch, 'externalApi') &&
      !controller.isMainSender(evt.sender)
    ) {
      throw new Error(UNAUTHORIZED);
    }
    return controller.setConfig(patch);
  });

  ipcMain.handle('pet:get-state', (evt) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    return controller.getState();
  });

  /** Both the pet window (animation assets) and settings need this list. */
  ipcMain.handle('pet:list-packs', (evt) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    return controller.listPacks();
  });

  /** Read-only local API runtime info; the token stays in pet-api.json. */
  ipcMain.handle('pet:api-info', (evt) => {
    if (!controller.isMainSender(evt.sender)) throw new Error(UNAUTHORIZED);
    return controller.getApiInfo();
  });

  ipcMain.handle('pet:import-pack', async (evt) => {
    if (!controller.isMainSender(evt.sender)) throw new Error(UNAUTHORIZED);
    const main = controller.getMainWindow();
    if (!main || main.isDestroyed()) return { ok: false, error: '主窗口不可用' };
    const picked = await dialog.showOpenDialog(main, {
      title: '导入宠物动画包',
      buttonLabel: '导入',
      properties: ['openFile'],
      filters: [{ name: 'Sage 宠物动画包 (*.zip)', extensions: ['zip'] }],
    });
    if (picked.canceled || picked.filePaths.length === 0) return { ok: false, canceled: true };
    return controller.importPack(picked.filePaths[0]!);
  });

  ipcMain.handle('pet:export-pack', async (evt, payload: unknown) => {
    if (!controller.isMainSender(evt.sender)) throw new Error(UNAUTHORIZED);
    const id = packIdOf(payload);
    if (!id) return { ok: false, error: '缺少动画包 id' };
    const main = controller.getMainWindow();
    if (!main || main.isDestroyed()) return { ok: false, error: '主窗口不可用' };
    const picked = await dialog.showSaveDialog(main, {
      title: '导出宠物动画包',
      defaultPath: `${id}.zip`,
      filters: [{ name: 'Sage 宠物动画包 (*.zip)', extensions: ['zip'] }],
    });
    if (picked.canceled || !picked.filePath) return { ok: false, canceled: true };
    return controller.exportPack(id, picked.filePath);
  });

  ipcMain.handle('pet:delete-pack', (evt, payload: unknown) => {
    if (!controller.isMainSender(evt.sender)) throw new Error(UNAUTHORIZED);
    const id = packIdOf(payload);
    if (!id) return { ok: false, error: '缺少动画包 id' };
    return controller.deletePack(id);
  });

  ipcMain.on('pet:ready', (evt) => {
    if (isPet(evt)) controller.windowReady(evt.sender);
  });

  ipcMain.on('pet:open-session', (evt, payload: unknown) => {
    if (isPet(evt)) controller.openSession(sessionIdOf(payload));
  });

  ipcMain.on('pet:open-settings', (evt) => {
    if (isPet(evt)) controller.openSettings();
  });

  ipcMain.on('pet:show-menu', (evt) => {
    if (isPet(evt)) controller.showMenu(evt.sender);
  });

  ipcMain.on('pet:drag-start', (evt) => {
    if (isPet(evt)) controller.startDrag(evt.sender);
  });

  ipcMain.on('pet:drag-move', (evt) => {
    if (isPet(evt)) controller.moveDrag(evt.sender);
  });

  ipcMain.on('pet:drag-end', (evt) => {
    if (isPet(evt)) controller.endDrag(evt.sender);
  });

  ipcMain.on('pet:reset-position', (evt) => {
    if (isAllowed(evt)) controller.resetPosition();
  });

  ipcMain.on('pet:set-panel', (evt, payload: { open?: unknown }) => {
    if (isPet(evt)) controller.setPanelOpen(evt.sender, payload?.open === true);
  });

  ipcMain.on('pet:toggle-panel', (evt) => {
    if (isPet(evt)) controller.togglePanel(evt.sender);
  });

  ipcMain.on('pet:pat', (evt) => {
    if (isPet(evt)) controller.recordPat();
  });

  ipcMain.on('pet:report-tasks', (evt, tasks: unknown) => {
    if (controller.isMainSender(evt.sender)) controller.reportTasks(tasks);
  });

  ipcMain.on('pet:hide', (evt) => {
    if (isPet(evt)) controller.hideForNow(evt.sender);
  });
}

/**
 * Remove every pet channel. `disposePet()` nulls the controller but a later
 * `initPet()` (e.g. macOS activate after the window was closed) would
 * otherwise call `ipcMain.handle` on already-registered channels and throw.
 */
export function unregisterPetIpc(): void {
  for (const channel of PET_INVOKE_CHANNELS) ipcMain.removeHandler(channel);
  for (const channel of PET_EVENT_CHANNELS) ipcMain.removeAllListeners(channel);
}
