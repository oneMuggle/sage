/**
 * Pet subsystem singleton.
 *
 * Initialized once after the main window exists; tray and main.ts use the
 * getter to avoid a circular import through mainWindow.
 */

import { PetController, type PetControllerOptions } from './controller';
import { registerPetIpc } from './ipc';

let controller: PetController | null = null;

export function initPet(options: PetControllerOptions): PetController {
  if (controller) return controller;
  controller = new PetController(options);
  registerPetIpc(controller);
  controller.init();
  return controller;
}

export function getPetController(): PetController | null {
  return controller;
}

export function disposePet(): void {
  controller?.dispose();
  controller = null;
}
