import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  BrowserWindow: class {},
  Menu: { buildFromTemplate: vi.fn() },
  dialog: {},
  shell: {},
  app: {},
  screen: { getCursorScreenPoint: vi.fn(), getDisplayNearestPoint: vi.fn() },
}));

vi.mock('../logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import { compatibilityEnabled } from '../pet/windows';
import type { PetConfig } from '../pet/types';

function config(mode: PetConfig['compatibilityMode']): PetConfig {
  return { compatibilityMode: mode } as PetConfig;
}

afterEach(() => {
  delete process.env.SAGE_PET_TRANSPARENCY_EXPERIMENT;
});

describe('compatibilityEnabled', () => {
  it('always uses the opaque window on legacy Windows', () => {
    expect(compatibilityEnabled(config('auto'), true)).toBe(true);
    expect(compatibilityEnabled(config('off'), true)).toBe(true);
    expect(compatibilityEnabled(config('on'), true)).toBe(true);
  });

  it('honors the setting on modern platforms', () => {
    expect(compatibilityEnabled(config('on'), false)).toBe(true);
    expect(compatibilityEnabled(config('off'), false)).toBe(false);
    expect(compatibilityEnabled(config('auto'), false)).toBe(false);
  });

  it('honors the setting on legacy Windows only under the transparency experiment', () => {
    process.env.SAGE_PET_TRANSPARENCY_EXPERIMENT = '1';
    expect(compatibilityEnabled(config('on'), true)).toBe(true);
    expect(compatibilityEnabled(config('off'), true)).toBe(false);
    expect(compatibilityEnabled(config('auto'), true)).toBe(false);
  });
});
