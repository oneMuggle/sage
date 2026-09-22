/**
 * r97: demoFlag 单测——isDemoMode 优先级链：override > electronAPI 标志 > settings store。
 */
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';

const state = vi.hoisted(() => ({
  override: undefined as boolean | undefined,
  storeDemo: false,
}));

vi.mock('../demoRuntime', () => ({
  getDemoModeOverride: () => state.override,
  setDemoModeOverride: (v: boolean) => {
    state.override = v;
  },
}));

vi.mock('../../../features/manage-settings/settingsStore', () => ({
  useSettingsStore: {
    getState: () => ({ settings: { demoMode: state.storeDemo } }),
  },
}));

import { isDemoMode } from '../demoFlag';
import { setDemoModeOverride } from '../demoRuntime';

beforeEach(() => {
  state.override = undefined;
  state.storeDemo = false;
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isDemoMode 优先级', () => {
  it('override=true 最高优先（其余全关仍为真）', () => {
    setDemoModeOverride(true);
    expect(isDemoMode()).toBe(true);
  });

  it('override=false 压过 electronAPI 与 store 的真值', () => {
    state.storeDemo = true;
    vi.stubGlobal('window', { electronAPI: { demoMode: true } });
    setDemoModeOverride(false);
    expect(isDemoMode()).toBe(false);
  });

  it('无 override 时读 electronAPI.demoMode', () => {
    vi.stubGlobal('window', { electronAPI: { demoMode: true } });
    expect(isDemoMode()).toBe(true);
  });

  it('无 override 无标志时回退 settings store', () => {
    state.storeDemo = true;
    expect(isDemoMode()).toBe(true);
  });

  it('全关为假（无 window 环境不炸）', () => {
    expect(isDemoMode()).toBe(false);
  });
});
