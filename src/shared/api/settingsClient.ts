/**
 * 前端 settings 客户端 — IPC 封装 + 5s 超时降级
 *
 * 失败语义：
 * - 读：返回 null（不抛）
 * - 写：静默（不抛，写入失败由 console.warn 记录）
 *
 * 设计理由：UI 永不阻塞；后端不可用时自动回退到 localStorage 缓存。
 */
import type { AppSettings } from '../../entities/setting/types';

import { invoke } from './desktopInvoke';

export const LOAD_TIMEOUT_MS = 5000;

export type PreferenceKey = 'app_settings' | 'theme_mode' | 'current_session_id';

/**
 * 5s IPC 超时 + 清理 timer 句柄。
 *
 * Promise.race 完成后必须 clearTimeout，否则未消费的 timer 会在 5s 后触发 reject，
 * 虽然不影响已 settled 的 Promise，但会累积 timer churn（每用户操作 ~1 个）。
 */
async function ipcCall<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  let timeoutId: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      invoke<T>(cmd, args ?? {}),
      new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('IPC timeout')), LOAD_TIMEOUT_MS);
      }),
    ]);
  } catch (e) {
    console.warn(`[settingsClient] ${cmd} failed:`, e);
    return null;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

export const settingsClient = {
  async getSettings(): Promise<AppSettings | null> {
    const resp = await ipcCall<{ data: AppSettings | null }>('get_settings');
    return resp?.data ?? null;
  },

  async setSettings(partial: Partial<AppSettings>): Promise<void> {
    await ipcCall('set_settings', { ...partial });
  },

  async getPreference<T extends string = string>(key: PreferenceKey): Promise<T | null> {
    const resp = await ipcCall<{ value: T | null }>('get_preference', { key });
    return resp?.value ?? null;
  },

  async setPreference(key: PreferenceKey, value: string, category = 'ui'): Promise<void> {
    await ipcCall('set_preference', { key, value, value_type: 'string', category });
  },
};
