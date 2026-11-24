/**
 * 受控浏览器控制面客户端（M3）。
 *
 * 与 webAccessClient 同口径：Electron 走 electronAPI.backendRequest（主进程
 * 注入本地 bearer token、解析真实后端端口），dev 走 Vite 代理同源转发。
 * 路由定义见 backend/api/browser_use_routes.py。
 */

import { webAccessApiUrl } from './webAccessClient';
import { getWebAuthHeaders } from './webTransport';

export type BrowserControlState = 'agent' | 'paused' | 'user_takeover';

export interface BrowserControlSession {
  session_id: string;
  state: BrowserControlState;
  alive: boolean;
  browser_type?: string;
  headless?: boolean;
}

/** 受控浏览器使用偏好（GET/PUT /browser/use-config）。 */
export interface BrowserUseConfig {
  default_visible: boolean;
  step_thumbnails: boolean;
}

/** 持久站点策略（GET /browser/site-policies）。 */
export interface SitePolicy {
  domain: string;
  mode: 'allow' | 'block';
  updated_at: number;
}

/** 待确认项（GET /browser/confirmations）。不含内部请求指纹。 */
export interface BrowserPendingConfirmation {
  id: string;
  session_id: string;
  kind: 'site_access' | 'sensitive_action';
  code: string;
  domain: string;
  description: string;
  options: Array<'session' | 'always' | 'approve' | 'deny'>;
  screenshot_path: string;
  /** 后端内联的有界缩略图（data URL）；截图不可内联时缺省。 */
  thumbnail_data_url?: string;
  /** 有截图路径但无法生成缩略图（超出大小上限 / 解码失败）。 */
  thumbnail_unavailable?: boolean;
  created_at: number;
}

/** 浏览器动作审计记录（GET /browser/audit）。 */
export interface BrowserAuditEntry {
  id: number;
  session_id: string;
  ts: number;
  domain: string;
  tool: string;
  action: string;
  target_ref: string;
  target_desc: string;
  result: string;
  approval: string;
}

export type ConfirmationDecision = 'session' | 'always' | 'approve' | 'deny';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET') as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  // Electron：走主进程中继（注入本地 bearer token、解析真实后端端口）
  const bridge = typeof window !== 'undefined' ? window.electronAPI?.backendRequest : undefined;
  if (bridge) {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    return bridge<T>({ method, path, body });
  }
  // 浏览器：Vite 代理（dev）或网页模式同源直连（token 由 ?token= 注入）
  const response = await fetch(webAccessApiUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...getWebAuthHeaders(),
      ...(init?.headers ?? {}),
    },
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

/** 读取受控浏览器使用偏好（缺省按开启处理由后端负责）。 */
export async function fetchBrowserUseConfig(): Promise<BrowserUseConfig> {
  return requestJson('/api/v1/browser/use-config');
}

/** 更新使用偏好；未提供的字段保持不变，返回更新后的完整配置。 */
export async function updateBrowserUseConfig(
  patch: Partial<BrowserUseConfig>,
): Promise<BrowserUseConfig> {
  return requestJson('/api/v1/browser/use-config', {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

/** 列举持久站点策略。 */
export async function fetchSitePolicies(): Promise<SitePolicy[]> {
  const data = await requestJson<{ policies?: SitePolicy[] }>('/api/v1/browser/site-policies');
  return data.policies ?? [];
}

/** 写入一条持久站点策略（allow / block）。 */
export async function setSitePolicy(domain: string, mode: 'allow' | 'block'): Promise<SitePolicy> {
  return requestJson('/api/v1/browser/site-policies/' + encodeURIComponent(domain), {
    method: 'PUT',
    body: JSON.stringify({ mode }),
  });
}

/** 删除一条持久站点策略（不存在 → 后端 404）。 */
export async function deleteSitePolicy(domain: string): Promise<void> {
  await requestJson('/api/v1/browser/site-policies/' + encodeURIComponent(domain), {
    method: 'DELETE',
  });
}

/** 列举待确认项；传 sessionId 时只返回该会话的条目。 */
export async function fetchPendingConfirmations(
  sessionId?: string,
): Promise<BrowserPendingConfirmation[]> {
  const query = sessionId ? '?session_id=' + encodeURIComponent(sessionId) : '';
  const data = await requestJson<{ confirmations?: BrowserPendingConfirmation[] }>(
    '/api/v1/browser/confirmations' + query,
  );
  return data.confirmations ?? [];
}

/** 裁决一条待确认项；后端会把控制状态恢复为 agent。 */
export async function resolveConfirmation(
  id: string,
  decision: ConfirmationDecision,
): Promise<{
  confirmation_id: string;
  kind: string;
  decision: string;
  control_state: 'agent';
}> {
  return requestJson('/api/v1/browser/confirmations/' + encodeURIComponent(id), {
    method: 'POST',
    body: JSON.stringify({ decision }),
  });
}

/** 读取最近的浏览器动作审计（倒序）。 */
export async function fetchBrowserAudit(
  sessionId?: string,
  limit?: number,
): Promise<BrowserAuditEntry[]> {
  const params: string[] = [];
  if (sessionId) params.push('session_id=' + encodeURIComponent(sessionId));
  if (limit !== undefined) params.push('limit=' + encodeURIComponent(String(limit)));
  const query = params.length > 0 ? '?' + params.join('&') : '';
  const data = await requestJson<{ entries?: BrowserAuditEntry[] }>(
    '/api/v1/browser/audit' + query,
  );
  return data.entries ?? [];
}
