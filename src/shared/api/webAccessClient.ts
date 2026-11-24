/**
 * 网页访问「已登录的网站」客户端（P0 登录体验）。
 *
 * 与 NetworkCredentialsSection 的 webAccessApiUrl 同口径：dev 走 Vite 代理，
 * Electron 产物直连本机后端。所有接口只返回脱敏字段，不含凭据值。
 */

import { getWebAuthHeaders } from './webTransport';

export interface SiteSession {
  domain: string;
  display_name: string;
  login_url: string;
  kind: 'cookie' | 'header';
  status: 'logged_in' | 'expired';
  expires_in_seconds: number | null;
  has_local_storage: boolean;
  origin_count: number;
  saved_at: number | null;
  source_profile?: string;
}

export interface SiteLoginTemplate {
  id: string;
  display_name: string;
  domains: string[];
  login_url: string;
  login_hint: string;
}

export interface SiteLoginJob {
  job_id: string;
  url: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  result?: { saved_domains?: string[] } | null;
  error?: string | null;
}

/** dev 走 Vite 代理；Electron 产物直连后端（与 mediaApi 同口径） */
export function webAccessApiUrl(path: string): string {
  if (typeof window !== 'undefined' && window.electronAPI) {
    return `http://127.0.0.1:8765${path}`;
  }
  return path;
}

/**
 * Electron：走主进程中继（注入本地 bearer token、解析真实后端端口）。
 * 渲染层裸 fetch 到受保护路径一定会被 LocalAuthMiddleware 401，新接入
 * 本机后端接口的客户端必须复用本函数，不要直接 fetch。
 */
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET') as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
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
  const payload = (await response.json().catch(() => ({}))) as T & {
    error?: string;
    detail?: string;
  };
  if (!response.ok) {
    throw new Error(payload?.error || payload?.detail || `HTTP ${response.status}`);
  }
  return payload;
}

/** 409 并发登录：不同站点已有登录窗口在等待。 */
export function isLoginInProgressError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes('login_in_progress');
}

export async function fetchSiteSessions(): Promise<SiteSession[]> {
  const data = await requestJson<{ sites?: SiteSession[] }>('/api/v1/web-access/sites');
  return data.sites ?? [];
}

export async function fetchSiteLoginTemplates(): Promise<SiteLoginTemplate[]> {
  const data = await requestJson<{ templates?: SiteLoginTemplate[] }>(
    '/api/v1/web-access/site-templates',
  );
  return data.templates ?? [];
}

export async function startSiteLogin(url: string): Promise<string> {
  // 调用方是用户的显式点击（设置页「登录网站」/ 聊天登录卡），视为本次
  // EXTERNAL 调用的批准；DISCUSS/PLAN 模式仍由 PermissionEngine 拒绝。
  const data = await requestJson<{
    job_id?: string;
    approval_required?: boolean;
    error?: string;
  }>('/api/v1/web-access/sites/login', {
    method: 'POST',
    body: JSON.stringify({ url, approved: true }),
  });
  if (data.approval_required) throw new Error('permission_approval_required');
  if (!data.job_id) throw new Error(data.error || 'missing_job_id');
  return data.job_id;
}

export interface SiteSessionVerify {
  domain: string;
  url: string;
  status: 'logged_in' | 'login_required' | 'unknown';
  checked_at: number;
  error?: string;
}

export interface BrowserExtensionDevice {
  device_id: string;
  label: string;
  created_at: number;
  last_seen_at: number;
  connected: boolean;
  sharing: boolean;
}

export interface BrowserExtensionShared {
  device_id: string;
  origin: string;
  host: string;
  title: string;
  shared_at: number;
}

export interface BrowserExtensionStatus {
  devices: BrowserExtensionDevice[];
  connected: boolean;
  shared: BrowserExtensionShared | null;
  base_url: string;
  extension_dir: string | null;
}

export interface BrowserExtensionPairingCode {
  code: string;
  expires_at: number;
  base_url: string;
  extension_dir: string | null;
}

export async function verifySiteSession(domain: string): Promise<SiteSessionVerify> {
  return requestJson<SiteSessionVerify>('/api/v1/web-access/sites/verify', {
    method: 'POST',
    body: JSON.stringify({ domain }),
  });
}

export async function fetchBrowserExtensionStatus(): Promise<BrowserExtensionStatus> {
  return requestJson<BrowserExtensionStatus>('/api/v1/web-access/browser-extension/status');
}

export async function createBrowserExtensionPairingCode(): Promise<BrowserExtensionPairingCode> {
  return requestJson<BrowserExtensionPairingCode>(
    '/api/v1/web-access/browser-extension/pairing-code',
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export async function revokeBrowserExtensionDevice(deviceId: string): Promise<void> {
  await requestJson(
    `/api/v1/web-access/browser-extension/devices/${encodeURIComponent(deviceId)}`,
    { method: 'DELETE' },
  );
}

export async function getSiteLoginJob(jobId: string): Promise<SiteLoginJob> {
  return requestJson<SiteLoginJob>(`/api/v1/web-access/sites/login/${encodeURIComponent(jobId)}`);
}

export async function deleteSiteSession(domain: string): Promise<void> {
  await requestJson(`/api/v1/web-access/sites/${encodeURIComponent(domain)}`, {
    method: 'DELETE',
  });
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

// ── 浏览器多账号（2026-11-20 browser-multi-account） ──────────────

export interface BrowserAccount {
  id: string;
  label: string;
  domain: string;
  color: string | null;
  notes: string | null;
  is_default: boolean;
  created_at: number;
  updated_at: number;
}

export interface AccountSwitchResult {
  ok: boolean;
  account_id: string;
  label: string;
  domain: string;
  swapped_domains: string[];
  message: string;
}

export async function fetchBrowserAccounts(domain?: string): Promise<BrowserAccount[]> {
  const query = domain ? `?domain=${encodeURIComponent(domain)}` : '';
  const data = await requestJson<{ accounts?: BrowserAccount[] }>(
    `/api/v1/browser-accounts${query}`,
  );
  return data.accounts ?? [];
}

export async function createBrowserAccount(input: {
  label: string;
  domain: string;
  color?: string;
  notes?: string;
  is_default?: boolean;
}): Promise<BrowserAccount> {
  const data = await requestJson<{ account?: BrowserAccount }>('/api/v1/browser-accounts', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  if (!data.account) throw new Error('missing_account');
  return data.account;
}

export async function updateBrowserAccount(
  accountId: string,
  patch: { label?: string; color?: string; notes?: string; is_default?: boolean },
): Promise<BrowserAccount> {
  const data = await requestJson<{ account?: BrowserAccount }>(
    `/api/v1/browser-accounts/${encodeURIComponent(accountId)}`,
    { method: 'PUT', body: JSON.stringify(patch) },
  );
  if (!data.account) throw new Error('missing_account');
  return data.account;
}

export async function deleteBrowserAccount(accountId: string): Promise<void> {
  await requestJson(`/api/v1/browser-accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  });
}

export async function switchBrowserAccount(
  accountId: string,
  browserId?: string,
): Promise<AccountSwitchResult> {
  return requestJson<AccountSwitchResult>('/api/v1/browser-accounts/switch', {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId, browser_id: browserId }),
  });
}

export async function startAccountLogin(input: {
  url: string;
  accountId?: string;
  accountLabel?: string;
}): Promise<{ jobId: string; accountId: string | null }> {
  const data = await requestJson<{
    job_id?: string;
    account_id?: string | null;
    error?: string;
  }>('/api/v1/browser-accounts/login', {
    method: 'POST',
    body: JSON.stringify({
      url: input.url,
      account_id: input.accountId,
      account_label: input.accountLabel,
      approved: true,
    }),
  });
  if (!data.job_id) throw new Error(data.error || 'missing_job_id');
  return { jobId: data.job_id, accountId: data.account_id ?? null };
}

/**
 * 轮询登录任务直到成功/失败/超时。
 *
 * 默认每 2s 一次、最多 5 分钟——与后端 browser_login 的等待窗口一致。
 */
export async function waitForSiteLogin(
  jobId: string,
  options: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<SiteLoginJob> {
  const intervalMs = options.intervalMs ?? 2000;
  const timeoutMs = options.timeoutMs ?? 330000;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (options.signal?.aborted) throw new Error('aborted');
    const job = await getSiteLoginJob(jobId);
    if (job.status === 'success' || job.status === 'failed') return job;
    if (Date.now() > deadline) throw new Error('login_timeout');
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
