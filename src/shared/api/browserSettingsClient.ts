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
