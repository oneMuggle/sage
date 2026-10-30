/**
 * 网页访问「已登录的网站」客户端（P0 登录体验）。
 *
 * 与 NetworkCredentialsSection 的 webAccessApiUrl 同口径：dev 走 Vite 代理，
 * Electron 产物直连本机后端。所有接口只返回脱敏字段，不含凭据值。
 */

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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET') as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  // Electron：走主进程中继（注入本地 bearer token、解析真实后端端口）
  const bridge =
    typeof window !== 'undefined' ? window.electronAPI?.backendRequest : undefined;
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
  const data = await requestJson<{ job_id?: string }>('/api/v1/web-access/sites/login', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
  if (!data.job_id) throw new Error('missing_job_id');
  return data.job_id;
}

export async function getSiteLoginJob(jobId: string): Promise<SiteLoginJob> {
  return requestJson<SiteLoginJob>(
    `/api/v1/web-access/sites/login/${encodeURIComponent(jobId)}`,
  );
}

export async function deleteSiteSession(domain: string): Promise<void> {
  await requestJson(`/api/v1/web-access/sites/${encodeURIComponent(domain)}`, {
    method: 'DELETE',
  });
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
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
