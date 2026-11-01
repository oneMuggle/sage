/**
 * Regression: disposePet() must unregister the pet IPC channels so a later
 * initPet() (macOS activate after the window was closed) can register them
 * again instead of throwing "second handler for 'pet:get-config'".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { handlers, listeners } = vi.hoisted(() => ({
  handlers: new Map<string, unknown>(),
  listeners: new Map<string, unknown>(),
}));

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn((channel: string, handler: unknown) => {
      if (handlers.has(channel)) {
        throw new Error(`Attempted to register a second handler for '${channel}'`);
      }
      handlers.set(channel, handler);
    }),
    removeHandler: vi.fn((channel: string) => {
      handlers.delete(channel);
    }),
    on: vi.fn((channel: string, listener: unknown) => {
      listeners.set(channel, listener);
    }),
    removeAllListeners: vi.fn((channel: string) => {
      listeners.delete(channel);
    }),
  },
  dialog: { showOpenDialog: vi.fn(), showSaveDialog: vi.fn() },
}));

import { registerPetIpc, unregisterPetIpc } from '../pet/ipc';
import type { PetController } from '../pet/controller';

function fakeController(): PetController {
  return {} as unknown as PetController;
}

describe('pet IPC registration lifecycle', () => {
  beforeEach(() => {
    handlers.clear();
    listeners.clear();
    vi.clearAllMocks();
  });

  it('registers every pet channel', () => {
    registerPetIpc(fakeController());
    expect(handlers.size).toBe(8);
    expect(listeners.size).toBe(13);
  });

  it('unregisters cleanly and allows a fresh registration', () => {
    registerPetIpc(fakeController());
    unregisterPetIpc();
    expect(handlers.size).toBe(0);
    expect(listeners.size).toBe(0);

    expect(() => registerPetIpc(fakeController())).not.toThrow();
    expect(handlers.size).toBe(8);
    expect(listeners.size).toBe(13);
  });

  it('still rejects a duplicate registration when dispose was skipped', () => {
    registerPetIpc(fakeController());
    expect(() => registerPetIpc(fakeController())).toThrow(/second handler/);
  });
});
