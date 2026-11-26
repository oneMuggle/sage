/**
 * 浏览器选择 API 客户端。
 *
 * 与 webAccessClient 同口径：Electron 走主进程 backendRequest 中继（注入
 * 本地 bearer token；渲染层裸 fetch 会被 LocalAuthMiddleware 401），
 * 浏览器 dev 回退 Vite 代理。
 */

import { requestJson } from './webAccessClient';

export interface DiscoveredBrowser {
  name: string;
  path: string;
  version: string | null;
  isDefault: boolean;
}

export interface BrowserListResponse {
  browsers: DiscoveredBrowser[];
  userConfigured: string | null;
  embeddedAvailable: boolean;
}

export async function fetchBrowserList(): Promise<BrowserListResponse> {
  return requestJson<BrowserListResponse>('/api/v1/diagnostic/browser/list');
}

export async function setBrowserPath(path: string): Promise<{ success: boolean; error?: string }> {
  return requestJson('/api/v1/diagnostic/browser/path', {
    method: 'PUT',
    body: JSON.stringify({ path }),
  });
}

// ---------------------------------------------------------------------------
// 2026-11-20: 浏览器会话配置（P0-P3）
// ---------------------------------------------------------------------------

export interface BrowserConfig {
  maxSessions: number;
  lruEvict: boolean;
}

export interface BrowserSessionInfo {
  id: string;
  name: string;
  last_used_at: string;
  alive: boolean;
  persistent: boolean;
  profile_name: string;
  /** 启动该实例的聊天会话 id；空串 = 无归属（旧实例/基础设施）。 */
  owner?: string;
  /** 是否有浏览器工具正在使用该实例。 */
  busy?: boolean;
}

export interface BrowserStatusResponse {
  active: number;
  max: number;
  lruEvict: boolean;
  sessions: BrowserSessionInfo[];
}

export async function fetchBrowserConfig(): Promise<BrowserConfig> {
  return requestJson<BrowserConfig>('/api/v1/browser/config');
}

export async function setBrowserConfig(config: Partial<BrowserConfig>): Promise<BrowserConfig> {
  return requestJson<BrowserConfig>('/api/v1/browser/config', {
    method: 'PUT',
    body: JSON.stringify({
      max_sessions: config.maxSessions,
      lru_evict: config.lruEvict,
    }),
  });
}

export async function fetchBrowserStatus(): Promise<BrowserStatusResponse> {
  return requestJson<BrowserStatusResponse>('/api/v1/browser/status');
}

export async function updateSessionName(
  browserId: string,
  name: string,
): Promise<{ ok: boolean; browser_id: string; name: string }> {
  return requestJson(`/api/v1/browser/${encodeURIComponent(browserId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
}
