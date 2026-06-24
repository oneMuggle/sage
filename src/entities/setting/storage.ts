/**
 * Settings 持久化 — 双写（localStorage 同步 + 后端异步）+ 自动迁移
 *
 * 加载策略：后端 > localStorage > DEFAULT_SETTINGS
 * 写入策略：同步写 cache + 异步推后端
 * 迁移策略：首次后端无值 + localStorage 有值 + 未标记迁移 → 自动上传
 */
import { settingsClient } from '../../shared/api/settingsClient';

import { AppSettings, DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from './types';

const CACHE_KEY = SETTINGS_STORAGE_KEY;
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';
const CACHE_RETENTION_DAYS = 7;

function readLocalCacheSync(): Partial<AppSettings> | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as Partial<AppSettings>) : null;
  } catch {
    return null;
  }
}

function writeLocalCacheSync(data: AppSettings): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(data));
  } catch {
    // 静默
  }
}

function isRetentionExpired(): boolean {
  try {
    const marker = localStorage.getItem(MIGRATION_MARKER);
    if (!marker) return false;
    const markedAt = new Date(marker).getTime();
    return Date.now() - markedAt > CACHE_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function cleanupLocalCacheIfExpired(): void {
  if (isRetentionExpired()) {
    try {
      localStorage.removeItem(CACHE_KEY);
      localStorage.removeItem(MIGRATION_MARKER);
    } catch {
      // 静默
    }
  }
}

async function maybeAutoMigrate(remote: AppSettings | null): Promise<void> {
  if (remote) return; // 后端有数据，无需迁移

  const local = readLocalCacheSync();
  if (!local) return; // local 也没有，跳过

  const marker = (() => {
    try {
      return localStorage.getItem(MIGRATION_MARKER);
    } catch {
      return null;
    }
  })();
  if (marker) return; // 已迁移过

  try {
    await settingsClient.setSettings({ ...DEFAULT_SETTINGS, ...local });
    try {
      localStorage.setItem(MIGRATION_MARKER, new Date().toISOString());
    } catch {
      // 静默
    }
  } catch {
    // 静默失败，下次启动重试
  }
}

function mergeWithDefaults(partial: Partial<AppSettings>): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    endpoints: partial.endpoints ?? DEFAULT_SETTINGS.endpoints,
    modelSelections: partial.modelSelections ?? DEFAULT_SETTINGS.modelSelections,
    version: partial.version ?? SETTINGS_VERSION,
  };
}

/**
 * 加载 settings：后端 → localStorage → DEFAULT_SETTINGS
 * 首次加载会触发自动迁移
 *
 * 合并策略（v3.1 修复数据丢失 bug）：
 *   - 后端返回部分数据时（如只有 model_selections 没有 endpoints），
 *     先和 localStorage 缓存合并（保留本地已有的 endpoints），
 *     再和 DEFAULT_SETTINGS 合并（补全缺失字段）。
 *   - 避免「后端缺字段 → 覆盖本地完整数据 → 数据丢失」的问题。
 */
export async function loadSettings(): Promise<AppSettings> {
  cleanupLocalCacheIfExpired();

  const remote = await settingsClient.getSettings();
  if (remote) {
    // 先和 local cache 合并（保留本地已有但后端缺失的字段，如 endpoints）
    const local = readLocalCacheSync() ?? {};
    const merged = mergeWithDefaults({ ...local, ...remote });
    writeLocalCacheSync(merged);
    return merged;
  }
  await maybeAutoMigrate(null);
  const local = readLocalCacheSync();
  return mergeWithDefaults(local ?? {});
}

/**
 * 同步写 local cache + 异步推后端
 */
export async function saveSettings(partial: Partial<AppSettings>): Promise<void> {
  const current = readLocalCacheSync() ?? DEFAULT_SETTINGS;
  // Partial 展开后所有字段 T|undefined，但 current 提供兜底，所以断言为完整 AppSettings
  const merged = {
    ...current,
    ...partial,
    endpoints: partial.endpoints ?? current.endpoints,
    modelSelections: partial.modelSelections ?? current.modelSelections,
    version: SETTINGS_VERSION,
  } as AppSettings;
  writeLocalCacheSync(merged);
  try {
    await settingsClient.setSettings(partial);
  } catch {
    // settingsClient 内部已 warn
  }
}

/**
 * 重置为默认值
 */
export async function resetSettings(): Promise<void> {
  writeLocalCacheSync({ ...DEFAULT_SETTINGS });
  try {
    await settingsClient.setSettings({ ...DEFAULT_SETTINGS });
  } catch {
    // 静默
  }
}

// 旧同步签名保留为 fallback（@deprecated；新代码用 async 版本）
/** @deprecated use loadSettings() async */
export function loadSettingsSync(): AppSettings {
  return mergeWithDefaults(readLocalCacheSync() ?? {});
}

// 注：原 migrateFromV1 / migrateFromV2 函数在新架构下不再需要：
// 后端只存 v3 格式；前端 localStorage 中的 v1/v2 数据由后端首次读 + 旧
// 客户端链路完成迁移后，本地不再有旧格式。YAGNI — 删。
// 如未来后端需回滚兼容老数据，再从 git history 恢复。
