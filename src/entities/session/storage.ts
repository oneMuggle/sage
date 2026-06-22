/**
 * Current session id 持久化 — 双写（localStorage 同步 + 后端异步）
 */
import { settingsClient } from '../../shared/api/settingsClient';

const CACHE_KEY = 'sage-current-session-id';

export async function loadCurrentSessionId(): Promise<string | null> {
  const remote = await settingsClient.getPreference<string>('current_session_id');
  if (remote) {
    try {
      localStorage.setItem(CACHE_KEY, remote);
    } catch {
      // 隐私模式
    }
    return remote;
  }
  try {
    return localStorage.getItem(CACHE_KEY) ?? null;
  } catch {
    return null;
  }
}

export async function saveCurrentSessionId(id: string | null): Promise<void> {
  try {
    if (id) {
      localStorage.setItem(CACHE_KEY, id);
    } else {
      localStorage.removeItem(CACHE_KEY);
    }
  } catch {
    // 静默
  }
  if (id) {
    await settingsClient.setPreference('current_session_id', id, 'session');
  }
  // 注：id=null 时不删后端（避免误清；后续可加 delete 端点）
}
