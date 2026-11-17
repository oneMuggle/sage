/**
 * 受控浏览器控制面客户端（M3）。
 *
 * 与 webAccessClient 同口径：Electron 走 electronAPI.backendRequest（主进程
 * 注入本地 bearer token、解析真实后端端口），dev 走 Vite 代理同源转发。
 * 路由定义见 backend/api/browser_use_routes.py。
 */

import { webAccessApiUrl } from './webAccessClient';

export type BrowserControlState = 'agent' | 'paused' | 'user_takeover';

export interface BrowserControlSession {
  session_id: string;
  state: BrowserControlState;
  alive: boolean;
  browser_type?: string;
  headless?: boolean;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET') as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  // Electron：走主进程中继（注入本地 bearer token、解析真实后端端口）
  const bridge = typeof window !== 'undefined' ? window.electronAPI?.backendRequest : undefined;
  if (bridge) {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    return bridge<T>({ method, path, body });
  }
  // 浏览器 dev：Vite 代理同源转发
  const response = await fetch(webAccessApiUrl(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  const payload = (await response.json().catch(() => ({}))) as T & { error?: string };
  if (!response.ok) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload;
}

/** 列举 manager 中的浏览器会话及其实时控制状态。 */
export async function fetchBrowserControlSessions(): Promise<BrowserControlSession[]> {
  const data = await requestJson<{ sessions?: BrowserControlSession[] }>('/api/v1/browser/control');
  return data.sessions ?? [];
}

/** 查询单个会话的控制状态；未知会话也返回 200 + agent。 */
export async function fetchBrowserControl(
  sessionId: string,
): Promise<{ session_id: string; state: BrowserControlState; known: boolean }> {
  return requestJson('/api/v1/browser/control/' + encodeURIComponent(sessionId));
}

/** pause / resume / takeover / return：更新会话控制状态。 */
export async function setBrowserControl(
  sessionId: string,
  action: 'pause' | 'resume' | 'takeover' | 'return',
): Promise<{ session_id: string; state: BrowserControlState }> {
  return requestJson('/api/v1/browser/control/' + encodeURIComponent(sessionId), {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}
