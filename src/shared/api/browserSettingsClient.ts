/**
 * 浏览器选择 API 客户端。
 *
 * 与 webAccessClient 同口径：dev 走 Vite 代理，Electron 走 electronAPI.backendRequest。
 */

import { webAccessApiUrl } from './webAccessClient';

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
  const res = await fetch(webAccessApiUrl('/api/v1/diagnostic/browser/list'), {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function setBrowserPath(path: string): Promise<{ success: boolean; error?: string }> {
  const res = await fetch(webAccessApiUrl('/api/v1/diagnostic/browser/path'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
