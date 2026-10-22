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

export function formatCurrentSessionStorageSummary(id: string | null): string {
  const cached = (() => {
    try {
      return localStorage.getItem(CACHE_KEY);
    } catch {
      /* v8 ignore next */
      return null;
    }
  })();
  return `${CACHE_KEY} · current=${id ?? 'none'} · cached=${cached ?? 'none'}`;
}

export function formatCurrentSessionStorageJson(id: string | null): string {
  const cached = (() => {
    try {
      return localStorage.getItem(CACHE_KEY);
    } catch {
      /* v8 ignore next */
      return null;
    }
  })();
  return JSON.stringify(
    {
      cacheKey: CACHE_KEY,
      currentSessionId: id,
      cachedSessionId: cached,
    },
    null,
    2,
  );
}

export function auditSessionStorageGovernance(
  state: {
    hasSessionId?: boolean;
    storageValid?: boolean;
  } = {},
): {
  module: 'src/entities/session/storage.ts';
  phase: 'P154';
  hasSessionId: boolean;
  storageValid: boolean;
  healthy: boolean;
} {
  const hasSessionId = state.hasSessionId !== false;
  const storageValid = state.storageValid !== false;
  return {
    module: 'src/entities/session/storage.ts',
    phase: 'P154',
    hasSessionId,
    storageValid,
    healthy: storageValid,
  };
}
