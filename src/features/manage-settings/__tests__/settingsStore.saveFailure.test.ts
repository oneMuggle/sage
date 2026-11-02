/**
 * settingsStore 保存失败可见性（2026-11-02）。
 *
 * 背景：saveSettings 此前静默吞掉后端 PUT 失败，用户看到设置页显示新值，
 * 重启后却回到旧值。本轮改为 saveSettings 返回布尔结果，store 在失败时
 * 弹 toast（5 秒节流，避免连续输入刷屏）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  saveSettings: vi.fn(),
  saveSettingsStrict: vi.fn(),
  loadSettings: vi.fn(),
  resetSettings: vi.fn(),
  toastError: vi.fn(),
  translateStatic: vi.fn((key: string) => `t:${key}`),
}));

vi.mock('../../../entities/setting/storage', () => ({
  loadSettings: (...args: unknown[]) => mocks.loadSettings(...args),
  resetSettings: (...args: unknown[]) => mocks.resetSettings(...args),
  saveSettings: (...args: unknown[]) => mocks.saveSettings(...args),
  saveSettingsStrict: (...args: unknown[]) => mocks.saveSettingsStrict(...args),
}));

vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => mocks.toastError(...args) },
}));

vi.mock('../../../shared/lib/i18n', () => ({
  translateStatic: (key: string) => mocks.translateStatic(key),
}));

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettingsStore } from '../settingsStore';

describe('settingsStore save failure visibility', () => {
  // 2026-11-02: 每个测试递增时间，避免模块级 lastSaveFailureToastAt 跨测试污染。
  // 步长 1_000_000ms 远大于 SAVE_FAILURE_TOAST_INTERVAL_MS（5000）。
  let currentTime = 0;

  beforeEach(() => {
    currentTime += 1_000_000;
    vi.useFakeTimers();
    vi.setSystemTime(currentTime);
    mocks.saveSettings.mockReset().mockResolvedValue(true);
    mocks.toastError.mockReset();
    mocks.translateStatic.mockClear();
    useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS }, isLoading: false });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('保存成功时不提示', async () => {
    await useSettingsStore.getState().updateSettings({ maxContext: 8000 });

    expect(mocks.saveSettings).toHaveBeenCalledWith({ maxContext: 8000 });
    expect(mocks.toastError).not.toHaveBeenCalled();
  });

  it('保存失败时提示并保留乐观更新的本地状态', async () => {
    mocks.saveSettings.mockResolvedValue(false);

    await useSettingsStore.getState().updateSettings({ maxContext: 8000 });

    expect(mocks.toastError).toHaveBeenCalledTimes(1);
    expect(mocks.toastError).toHaveBeenCalledWith('t:settings.save_failed_sync');
    expect(useSettingsStore.getState().settings.maxContext).toBe(8000);
  });

  it('5 秒内的连续失败只提示一次', async () => {
    mocks.saveSettings.mockResolvedValue(false);

    await useSettingsStore.getState().updateSettings({ maxContext: 8000 });
    await useSettingsStore.getState().updateSettings({ maxContext: 9000 });
    expect(mocks.toastError).toHaveBeenCalledTimes(1);

    vi.setSystemTime(currentTime + 6001);
    await useSettingsStore.getState().updateSettings({ maxContext: 10000 });
    expect(mocks.toastError).toHaveBeenCalledTimes(2);
  });
});
