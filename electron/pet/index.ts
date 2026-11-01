/**
 * Pet subsystem singleton.
 *
 * Initialized once after the main window exists; tray and main.ts use the
 * getter to avoid a circular import through mainWindow.
 */

import { PetController, type PetControllerOptions } from './controller';
<<<<<<< HEAD
import { registerPetIpc } from './ipc';
=======
import { registerPetIpc, unregisterPetIpc } from './ipc';
>>>>>>> origin/main

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
<<<<<<< HEAD
=======
  // A later initPet() (e.g. macOS activate after the window was closed) must
  // be able to register the same channels again.
  unregisterPetIpc();
>>>>>>> origin/main
}
