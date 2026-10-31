/**
 * Whitelisted pet IPC.
 *
 * The pet window is deliberately NOT a trusted renderer for `sage:invoke` /
 * `sage:listen`; these channels are the only bridge it gets. Every handler
 * checks the sender window.
 */

import { ipcMain, type IpcMainEvent, type IpcMainInvokeEvent } from 'electron';

import type { PetController } from './controller';

const UNAUTHORIZED = '未授权的宠物窗口请求';

function sessionIdOf(payload: unknown): string | null {
  if (typeof payload === 'string') return payload;
  if (payload && typeof payload === 'object' && 'sessionId' in payload) {
    const value = (payload as { sessionId?: unknown }).sessionId;
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
    return controller.getConfig();
  });

  ipcMain.handle('pet:set-config', (evt, patch: unknown) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    return controller.setConfig(patch);
  });

  ipcMain.handle('pet:get-state', (evt) => {
    if (!isAllowed(evt)) throw new Error(UNAUTHORIZED);
    return controller.getState();
  });

  ipcMain.on('pet:ready', (evt) => {
    if (isPet(evt)) controller.windowReady();
  });

  ipcMain.on('pet:open-session', (evt, payload: unknown) => {
    if (isPet(evt)) controller.openSession(sessionIdOf(payload));
  });

  ipcMain.on('pet:open-settings', (evt) => {
    if (isPet(evt)) controller.openSettings();
  });

  ipcMain.on('pet:show-menu', (evt) => {
    if (isPet(evt)) controller.showMenu();
  });

  ipcMain.on('pet:drag-start', (evt) => {
    if (isPet(evt)) controller.startDrag();
  });

  ipcMain.on('pet:drag-move', (evt) => {
    if (isPet(evt)) controller.moveDrag();
  });

  ipcMain.on('pet:drag-end', (evt) => {
    if (isPet(evt)) controller.endDrag();
  });

  ipcMain.on('pet:reset-position', (evt) => {
    if (isAllowed(evt)) controller.resetPosition();
  });

  ipcMain.on('pet:set-panel', (evt, payload: { open?: unknown }) => {
    if (isPet(evt)) controller.setPanelOpen(payload?.open === true);
  });

  ipcMain.on('pet:hide', (evt) => {
    if (isPet(evt)) controller.hideForNow();
  });
}
