/**
 * Settings 持久化 — 双写（localStorage 同步 + 后端异步）+ 自动迁移
 *
 * 加载策略：后端 > localStorage > DEFAULT_SETTINGS
 * 写入策略：同步写 cache + 异步推后端
 * 迁移策略：首次后端无值 + localStorage 有值 + 未标记迁移 → 自动上传
 */
import { settingsClient } from '../../shared/api/settingsClient';

import { deepMerge } from './deepMerge';
import {
  AppSettings,
  DEFAULT_ORCH_SETTINGS,
  DEFAULT_SETTINGS,
  EndpointConfig,
  ModelSelections,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from './types';

const CACHE_KEY = SETTINGS_STORAGE_KEY;
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';
const CACHE_RETENTION_DAYS = 7;

// 2026-08-26: 前端 canonical 字段白名单 — 与后端 ``LEGAL_TOP_KEYS`` /
// ``LEGAL_ENDPOINT_KEYS`` 对齐, 防止 localStorage 历史残留 (memory_server_sync /
// local_model_path 等) 在 maybeAutoMigrate / saveSettings 重新上传到后端时
// 被 Pydantic validate_settings_shape 拒绝 (400 'unknown top-level field').
// 仅含前端当前 schema 接受且会发给后端的字段 — 与后端白名单同步.
const TOP_KEYS: ReadonlySet<keyof AppSettings> = new Set([
  'streaming',
  'autoMemory',
  'confirmDelete',
  'endpoints',
  'modelSelections',
  'maxContext',
  'temperature',
  'timezone',
  'wiki',
  'orch',
  'version',
  // 'memoryServerSync' 不在此白名单内 — 后端已下线该字段, 前端发出去会 400.
]);
const ENDPOINT_KEYS: ReadonlySet<keyof EndpointConfig> = new Set([
  'id',
  'name',
  'baseUrl',
  'apiKey',
  'protocol',
  'modelId',
  'discoveredModels',
  'lastDiscoveredAt',
  // 'localModelPath' 不在此白名单内 — UI 已隐藏, 后端白名单已收紧.
]);
const SNAKE_KEYS_TO_DROP: ReadonlySet<string> = new Set([
  // 历史 schema 的 snake_case 残留 — 后端 canonicalizer to_camel 会把它们翻成
  // camelCase 但仍不在 LEGAL_TOP_KEYS / LEGAL_ENDPOINT_KEYS, 触发 400. 直接
  // 在源头丢弃更安全.
  'memory_server_sync',
  'memoryServerSync',
  'local_model_path',
  'localModelPath',
  'max_iterations',
  'subagent_max_iterations',
  'compact_mode',
  'proxy_mode',
  'proxy_url',
  'tls_version',
]);

function sanitizeForBackend<T extends Partial<AppSettings>>(partial: T): T {
  // 防御性拷贝 + 字段级净化:
  // 1) 顶层: 只保留白名单内 key, 丢弃 snake_case 残留 (含 known-bad list).
  // 2) endpoints[*]: 同样只保留白名单内字段.
  // 不修改入参, 返回新对象.
  if (!partial || typeof partial !== 'object') return partial;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(partial as Record<string, unknown>)) {
    if (SNAKE_KEYS_TO_DROP.has(k)) continue;
    if (!TOP_KEYS.has(k as keyof AppSettings)) continue;
    if (k === 'endpoints' && Array.isArray(v)) {
      out[k] = (v as unknown[]).map((ep) => {
        if (!ep || typeof ep !== 'object') return ep;
        const cleanEp: Record<string, unknown> = {};
        for (const [ek, ev] of Object.entries(ep as Record<string, unknown>)) {
          if (SNAKE_KEYS_TO_DROP.has(ek)) continue;
          if (!ENDPOINT_KEYS.has(ek as keyof EndpointConfig)) continue;
          cleanEp[ek] = ev;
        }
        return cleanEp;
      });
    } else {
      out[k] = v;
    }
  }
  return out as T;
}

// 暴露给单测 (vitest) 验证 canonical 净化行为.
export const __test__sanitizeForBackend = sanitizeForBackend;
export const __test__SNAKE_KEYS_TO_DROP = SNAKE_KEYS_TO_DROP;

/**
 * 2026-08-26 (OWASP A02:2021): 从 localStorage 找回被后端 redact_secrets
 * 脱敏的 apiKey. 后端 GET 返回 ``{apiKey: "", hasApiKey: true}``; 若 local
 * 中相同 id 的 endpoint 还有非空 apiKey, 用本地值覆盖脱敏值, 让下游
 * deepMerge 拿到非冲突的字段, 避免 remote-wins 把真实 key 覆盖掉.
 *
 * 必须按 id 匹配 — 数组顺序不可靠 (loadSettings 跑过几次后端可能 reorder).
 *
 * 不会凭空捏造 key: 仅在 local 已有非空 apiKey 且 remote 显式标注
 * ``hasApiKey === true`` 时才还原. 若用户主动清空 key (local 也为空),
 * 保持空; 若后端没设 ``hasApiKey`` 字段 (历史响应), 不动 apiKey 避免覆盖真实值.
 *
 * 函数纯: 不修改入参, 返回新对象.
 */
export function restoreRedactedApiKeys(
  remote: Partial<AppSettings>,
  local: Partial<AppSettings>,
): Partial<AppSettings> {
  if (!remote || typeof remote !== 'object') return remote;
  const remoteEndpoints = Array.isArray(remote.endpoints) ? remote.endpoints : [];
  if (remoteEndpoints.length === 0) return remote;
  const localEndpoints = Array.isArray(local.endpoints) ? local.endpoints : [];
  if (localEndpoints.length === 0) return remote;
  const localById = new Map<string, EndpointConfig>();
  for (const ep of localEndpoints) {
    if (ep && typeof ep === 'object' && typeof ep.id === 'string') {
      localById.set(ep.id, ep);
    }
  }
  const restored = remoteEndpoints.map((re): EndpointConfig => {
    if (!re || typeof re !== 'object') return re as EndpointConfig;
    const r = re as Partial<EndpointConfig>;
    if (
      r.hasApiKey === true &&
      (r.apiKey === '' || r.apiKey === null || r.apiKey === undefined) &&
      typeof r.id === 'string'
    ) {
      const localEp = localById.get(r.id);
      if (localEp && typeof localEp.apiKey === 'string' && localEp.apiKey !== '') {
        return { ...(r as EndpointConfig), apiKey: localEp.apiKey };
      }
    }
    return re as EndpointConfig;
  });
  return { ...remote, endpoints: restored };
}

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
    // 2026-08-26: 先 canonical 净化, 防止 localStorage 旧字段 PUT → 400.
    await settingsClient.setSettings(sanitizeForBackend({ ...DEFAULT_SETTINGS, ...local }));
    try {
      localStorage.setItem(MIGRATION_MARKER, new Date().toISOString());
    } catch {
      // 静默
    }
  } catch {
    // 静默失败，下次启动重试
  }
}

// 导出为测试钩子（vitest 直接断言嵌套 merge 行为）。
export function mergeWithDefaults(partial: Partial<AppSettings>): AppSettings {
  // Task 1 round 1 (2026-08-24): endpoints / modelSelections 走 deepMerge 而非
  // 整体替换. 之前 ``partial.endpoints ?? DEFAULT_SETTINGS.endpoints`` 是 hard
  // replace — 用户的 partial 里只更新了一条 endpoint, 会把 DEFAULT 的其它默认
  // endpoint 全部丢掉, 新加默认 endpoint 时用户永远看不到.
  //
  // deepMerge 行为:
  // - 同 id endpoint → 字段级 merge (DEFAULT 字段 + 用户覆盖字段)
  // - 新 id (用户加的) → 追加
  // - DEFAULT 独有 id (用户在老 partial 没的) → 保留
  // 这与 loadSettings 的 remote + local 合并策略一致 (deepMerge remote-wins).
  const partialEndpoints = partial.endpoints;
  const mergedEndpoints =
    partialEndpoints === undefined
      ? DEFAULT_SETTINGS.endpoints
      : deepMerge<EndpointConfig[]>(DEFAULT_SETTINGS.endpoints, partialEndpoints, {
          policy: 'remote-wins',
        });

  const partialModelSelections = partial.modelSelections;
  const mergedModelSelections =
    partialModelSelections === undefined
      ? DEFAULT_SETTINGS.modelSelections
      : deepMerge<ModelSelections>(DEFAULT_SETTINGS.modelSelections, partialModelSelections, {
          policy: 'remote-wins',
        });

  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    endpoints: mergedEndpoints,
    modelSelections: mergedModelSelections,
    // Task 1 (2026-08-23): 缺省时区补 'Asia/Shanghai' — 与 DEFAULT_SETTINGS.timezone 对齐.
    timezone: partial.timezone ?? DEFAULT_SETTINGS.timezone,
    // 嵌套 merge：部分 orch 更新不丢其余键（同 endpoints 的既有 bug 防护）。
    orch: { ...DEFAULT_ORCH_SETTINGS, ...(partial.orch ?? {}) },
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

  let remote: AppSettings | null = null;
  try {
    remote = await settingsClient.getSettings();
  } catch (e: unknown) {
    console.error('[loadSettings] backend getSettings failed, falling back to local:', e);
  }

  if (remote) {
    // 远端成功 → 以远端为权威, local 仅作 merge 兜底
    const local = readLocalCacheSync() ?? {};
    // 2026-08-26 (OWASP A02:2021): 后端 redact_secrets 把 GET 响应里的
    // apiKey 替换成 "" + hasApiKey=true. deepMerge remote-wins 策略会用空字
    // 符串覆盖 local.apiKey, 用户每次启动都会丢 key. 这里按 endpoint id 从
    // local 把被脱敏的 apiKey 找回来, 再让 deepMerge 跑不冲突的值. plan §1:
    // "同步保留已有设置的 API key, 不因脱敏 GET 覆盖用户输入."
    const restoredRemote = restoreRedactedApiKeys(remote, local);
    const merged = deepMerge<Partial<AppSettings>>(local, restoredRemote, {
      policy: 'remote-wins',
    });
    const finalSettings = mergeWithDefaults(merged);
    writeLocalCacheSync(finalSettings);
    return finalSettings;
  }

  await maybeAutoMigrate(remote);

  const local = readLocalCacheSync();
  const finalSettings = mergeWithDefaults(local ?? {});
  writeLocalCacheSync(finalSettings);
  return finalSettings;
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
    // 2026-08-26: 同样净化 PUT 载荷, 防止带历史字段的 partial 触发 400.
    await settingsClient.setSettings(sanitizeForBackend(partial));
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
