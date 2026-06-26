/**
 * 自定义 CSS 主题 IPC 客户端
 *
 * 失败语义（与 settingsClient 对齐）：
 * - save / delete：写操作，失败时抛出（用户需要反馈）
 * - list：失败时返回 []（不阻塞 UI）
 * - get：失败时返回 null（不阻塞 UI）
 * - list / get 返回值经 zod schema 校验，脏数据被过滤
 */
import { themeCssPayloadSchema, type ThemeCssPayload } from '../../features/theme/themeCssTypes';

import { invoke } from './desktopInvoke';

export const themeCssClient = {
  async save(payload: ThemeCssPayload): Promise<{ id: string }> {
    return invoke<{ id: string }>('theme_save', { payload });
  },

  async list(): Promise<ThemeCssPayload[]> {
    try {
      const raw = await invoke<unknown[]>('theme_list', {});
      return raw
        .map((item) => themeCssPayloadSchema.safeParse(item))
        .filter((r) => r.success)
        .map((r) => (r as { success: true; data: ThemeCssPayload }).data);
    } catch (e) {
      console.warn('[themeCssClient] list failed:', e);
      return [];
    }
  },

  async delete(id: string): Promise<void> {
    await invoke('theme_delete', { id });
  },

  async get(id: string): Promise<ThemeCssPayload | null> {
    try {
      const raw = await invoke<unknown | null>('theme_get', { id });
      if (raw == null) return null;
      const result = themeCssPayloadSchema.safeParse(raw);
      return result.success ? result.data : null;
    } catch (e) {
      console.warn('[themeCssClient] get failed:', e);
      return null;
    }
  },
};
