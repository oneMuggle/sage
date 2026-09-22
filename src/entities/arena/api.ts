/**
 * Arena API 客户端 (2026-09-19)
 *
 * 消费 backend.api.arena_routes 提供的 REST 端点：
 *   /api/v1/arena/accounts*    账号池 CRUD / 隔离 / 启用
 *   /api/v1/arena/register*    单账号注册辅助（人工验证码，状态机）
 *   /api/v1/arena/observations 被动模型观测
 *   /api/v1/arena/registration/jobs* + /jobs/{id}/events 批量注册任务
 *   /api/v1/arena/draw/jobs* + /draws 抽卡任务与记录
 *   /api/v1/arena/token-window/* token 窗口状态（P5）
 *
 * 与 model-catalog/api.ts 同样走 ``backendRequest`` 漏斗 — 经 Electron
 * IPC relay 转发到本地 FastAPI 后端（仅 /api/v1/*）。
 */
import { backendRequest } from '../../shared/api/backendRequest';

const BASE = '/api/v1/arena';

// ---------- 类型 ----------

export interface ArenaAccount {
  id: string;
  email: string;
  state: 'available' | 'reserved' | 'degraded' | 'disabled' | 'destroyed';
  failure_count: number;
  last_used_at: string | null;
  isolated_at: string | null;
  created_at: string;
  notes: string | null;
}

export interface RegistrationStatus {
  registration_id: string;
  email: string;
  state:
    | 'awaiting_signup'
    | 'awaiting_verification'
    | 'verification_ready'
    | 'awaiting_password'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'expired';
  captcha_present: boolean;
  verification_link: string;
  email_filled: boolean;
  error: string;
  created_at: string;
  expires_in_sec: number;
  manual_hint: string;
}

export interface ModelVerdict {
  modelId: string | null;
  family: string | null;
  confidence: number;
  source: string | null;
  evidence_count?: number;
  observed_at?: string;
}

export interface ObservationsResponse {
  attached: boolean;
  verdicts: ModelVerdict[];
}

// ---------- 账号池 ----------

export async function listAccounts(): Promise<ArenaAccount[]> {
  return backendRequest<ArenaAccount[]>({ path: `${BASE}/accounts`, method: 'GET' });
}

export async function createAccount(email: string, password: string): Promise<ArenaAccount> {
  return backendRequest<ArenaAccount>({
    path: `${BASE}/accounts`,
    method: 'POST',
    body: { email, password },
  });
}

export async function deleteAccount(id: string): Promise<void> {
  await backendRequest<void>({
    path: `${BASE}/accounts/${encodeURIComponent(id)}`,
    method: 'DELETE',
  });
}

export async function isolateAccount(id: string): Promise<ArenaAccount> {
  return backendRequest<ArenaAccount>({
    path: `${BASE}/accounts/${encodeURIComponent(id)}/isolate`,
    method: 'POST',
  });
}

export async function enableAccount(id: string): Promise<ArenaAccount> {
  return backendRequest<ArenaAccount>({
    path: `${BASE}/accounts/${encodeURIComponent(id)}/enable`,
    method: 'POST',
  });
}

// ---------- 注册辅助 ----------

export async function startRegistration(): Promise<RegistrationStatus> {
  return backendRequest<RegistrationStatus>({
    path: `${BASE}/register/start`,
    method: 'POST',
  });
}

export async function getRegistration(): Promise<RegistrationStatus> {
  return backendRequest<RegistrationStatus>({
    path: `${BASE}/register/current`,
    method: 'GET',
  });
}

export async function openVerification(): Promise<RegistrationStatus> {
  return backendRequest<RegistrationStatus>({
    path: `${BASE}/register/current/open-verify`,
    method: 'POST',
  });
}

export async function setRegistrationPassword(
  password: string,
  manual = false,
): Promise<ArenaAccount> {
  return backendRequest<ArenaAccount>({
    path: `${BASE}/register/current/password`,
    method: 'POST',
    body: { password, manual },
  });
}

export async function cancelRegistration(): Promise<{ registration_id: string; state: string }> {
  return backendRequest<{ registration_id: string; state: string }>({
    path: `${BASE}/register/current/cancel`,
    method: 'POST',
  });
}

// ---------- 模型观测 ----------

export async function listObservations(limit = 20): Promise<ObservationsResponse> {
  return backendRequest<ObservationsResponse>({
    path: `${BASE}/observations?limit=${limit}`,
    method: 'GET',
  });
}

export async function attachObservation(browserId?: string): Promise<{ attached: boolean }> {
  return backendRequest<{ attached: boolean }>({
    path: `${BASE}/observations/attach`,
    method: 'POST',
    body: { browser_id: browserId ?? null },
  });
}

export async function detachObservation(): Promise<{ attached: boolean }> {
  return backendRequest<{ attached: boolean }>({
    path: `${BASE}/observations/detach`,
    method: 'POST',
  });
}

// ---------- 任务（注册 / 抽卡，JobStore 语义） ----------

export interface ArenaJobSnapshot {
  id: string;
  kind: string;
  status: 'running' | 'stopping' | 'done' | 'failed' | 'stopped';
  created_at: string;
  total: number;
  done: number;
  ok: number;
  failed: number;
  params: Record<string, unknown>;
  result_count: number;
  error: string;
  last_seq: number;
}

export interface ArenaJobEvent {
  seq: number;
  ts: string;
  level: 'info' | 'warn' | 'error';
  kind: string;
  message: string;
  data: Record<string, unknown>;
}

/** GET /jobs/{id}/events 返回 NDJSON 文本（responseType: 'text' 经 relay）。 */
export function parseJobEventsNdjson(text: string): ArenaJobEvent[] {
  const out: ArenaJobEvent[] = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const value = JSON.parse(trimmed) as Record<string, unknown>;
      if (
        typeof value.seq === 'number' &&
        typeof value.message === 'string' &&
        typeof value.kind === 'string'
      ) {
        out.push({
          seq: value.seq,
          ts: typeof value.ts === 'string' ? value.ts : '',
          level: (['info', 'warn', 'error'] as const).includes(value.level as never)
            ? (value.level as ArenaJobEvent['level'])
            : 'info',
          kind: value.kind,
          message: value.message,
          data: (value.data as Record<string, unknown>) ?? {},
        });
      }
    } catch {
      // 单行损坏跳过（NDJSON 容错）
    }
  }
  return out;
}

export interface StartRegistrationJobInput {
  count: number;
  concurrency?: number;
  proxy_mode?: 'off' | 'pool';
}

export async function startRegistrationJob(
  input: StartRegistrationJobInput,
): Promise<{ id: string; status: string }> {
  return backendRequest<{ id: string; status: string }>({
    path: `${BASE}/registration/jobs`,
    method: 'POST',
    body: { count: input.count, concurrency: input.concurrency, proxy_mode: input.proxy_mode },
  });
}

export async function getRegistrationJob(id: string): Promise<ArenaJobSnapshot> {
  return backendRequest<ArenaJobSnapshot>({
    path: `${BASE}/registration/jobs/${encodeURIComponent(id)}`,
    method: 'GET',
  });
}

export async function stopRegistrationJob(id: string): Promise<{ stopped: boolean }> {
  return backendRequest<{ stopped: boolean }>({
    path: `${BASE}/registration/jobs/${encodeURIComponent(id)}/stop`,
    method: 'POST',
  });
}

/** 导出注册产物（register_results.json 文本，浏览器端另存下载）。 */
export async function exportRegistrationJob(id: string): Promise<string> {
  return backendRequest<string>({
    path: `${BASE}/registration/jobs/${encodeURIComponent(id)}/export`,
    method: 'GET',
    responseType: 'text',
  });
}

export async function getRegistrationJobEvents(
  id: string,
  afterSeq = 0,
): Promise<ArenaJobEvent[]> {
  const text = await backendRequest<string>({
    path: `${BASE}/jobs/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`,
    method: 'GET',
    responseType: 'text',
  });
  return parseJobEventsNdjson(text);
}

// ---------- 抽卡 ----------

export interface ArenaDrawRow {
  account_id: string;
  email: string;
  model: string;
  internal: string;
  provider: string;
  session_id: string;
  run_id: string;
  kept: boolean;
  ok: boolean;
  error: string;
  reasoning: string | number;
  tokens_in: string | number;
  tokens_out: string | number;
  tier: string;
  setting_hints: string;
  switch: boolean;
  created_at: string;
}

export interface StartDrawJobInput {
  all_accounts?: boolean;
  account_ids?: string[];
  rounds_per_account?: number;
  keep_pattern?: string;
  miss_action?: 'archive' | 'keep' | 'delete';
  rename_hit?: boolean;
  want_reasoning?: boolean;
  require_reasoning?: boolean;
}

export async function startDrawJob(
  input: StartDrawJobInput,
): Promise<{ id: string; status: string }> {
  return backendRequest<{ id: string; status: string }>({
    path: `${BASE}/draw/jobs`,
    method: 'POST',
    body: input,
  });
}

export async function listDrawJobs(): Promise<ArenaJobSnapshot[]> {
  return backendRequest<ArenaJobSnapshot[]>({ path: `${BASE}/draw/jobs`, method: 'GET' });
}

export async function getDrawJob(id: string): Promise<ArenaJobSnapshot> {
  return backendRequest<ArenaJobSnapshot>({
    path: `${BASE}/draw/jobs/${encodeURIComponent(id)}`,
    method: 'GET',
  });
}

export async function stopDrawJob(id: string): Promise<{ stopped: boolean }> {
  return backendRequest<{ stopped: boolean }>({
    path: `${BASE}/draw/jobs/${encodeURIComponent(id)}/stop`,
    method: 'POST',
  });
}

export async function getDrawJobEvents(id: string, afterSeq = 0): Promise<ArenaJobEvent[]> {
  const text = await backendRequest<string>({
    path: `${BASE}/draw/jobs/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`,
    method: 'GET',
    responseType: 'text',
  });
  return parseJobEventsNdjson(text);
}

export async function listDraws(limit = 50): Promise<ArenaDrawRow[]> {
  return backendRequest<ArenaDrawRow[]>({ path: `${BASE}/draws?limit=${limit}`, method: 'GET' });
}

// ---------- token 窗口 ----------

export interface TokenWindowHealth {
  ready: boolean;
  count: number;
  error: string;
  exit_ip: string;
  ua: string;
  uptime: number;
  last_push_age: number | null;
}

export interface TokenWindowState {
  enabled: boolean;
  needed: boolean;
  reject_count: number;
  want_proxy: boolean;
  proxy_url: string;
  poll_interval_sec: number;
}

export async function tokenWindowHealth(): Promise<TokenWindowHealth> {
  return backendRequest<TokenWindowHealth>({
    path: `${BASE}/token-window/health`,
    method: 'GET',
  });
}

export async function tokenWindowState(): Promise<TokenWindowState> {
  return backendRequest<TokenWindowState>({
    path: `${BASE}/token-window/state`,
    method: 'GET',
  });
}
