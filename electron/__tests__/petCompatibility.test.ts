import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  BrowserWindow: class {},
  Menu: { buildFromTemplate: vi.fn() },
  dialog: {},
  shell: {},
  app: {},
  screen: { getCursorScreenPoint: vi.fn(), getDisplayNearestPoint: vi.fn() },
  systemPreferences: { isAeroGlassEnabled: vi.fn(() => true) },
}));

vi.mock('../logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import { compatibilityEnabled, type CompatContext } from '../pet/windows';
import type { PetConfig } from '../pet/types';

function config(mode: PetConfig['compatibilityMode']): PetConfig {
  return { compatibilityMode: mode } as PetConfig;
}

function context(legacyWindows: boolean, dwmComposition: boolean): CompatContext {
  return { legacyWindows, dwmComposition };
}

describe('compatibilityEnabled', () => {
  it('honors off as transparent on legacy Windows when DWM composition is available', () => {
    expect(compatibilityEnabled(config('off'), context(true, true))).toBe(false);
  });

  it('forces the opaque window on legacy Windows when DWM composition is unavailable', () => {
    expect(compatibilityEnabled(config('off'), context(true, false))).toBe(true);
  });

  it('keeps auto opaque on legacy Windows and on opaque everywhere', () => {
    expect(compatibilityEnabled(config('auto'), context(true, true))).toBe(true);
    expect(compatibilityEnabled(config('auto'), context(true, false))).toBe(true);
    expect(compatibilityEnabled(config('on'), context(true, true))).toBe(true);
    expect(compatibilityEnabled(config('on'), context(false, true))).toBe(true);
  });

  it('honors the setting on modern platforms', () => {
    expect(compatibilityEnabled(config('on'), context(false, true))).toBe(true);
    expect(compatibilityEnabled(config('off'), context(false, true))).toBe(false);
    expect(compatibilityEnabled(config('auto'), context(false, true))).toBe(false);
  });
});
