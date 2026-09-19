/**
 * Arena API 客户端 (2026-09-19)
 *
 * 消费 backend.api.arena_routes 提供的 REST 端点：
 *   /api/v1/arena/accounts*    账号池 CRUD / 隔离 / 启用
 *   /api/v1/arena/register*    单账号注册辅助（人工验证码，状态机）
 *   /api/v1/arena/observations 被动模型观测
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
