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

async function ipcCall<T>(cmd: string, args?: object): Promise<T | null> {
  try {
    return await Promise.race([
      invoke<T>(cmd, args ?? {}),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('IPC timeout')), LOAD_TIMEOUT_MS),
      ),
    ]);
  } catch (e) {
    console.warn(`[settingsClient] ${cmd} failed:`, e);
    return null;
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
