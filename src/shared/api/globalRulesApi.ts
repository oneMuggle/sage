/**
 * 全局规则（~/.sage/SAGE.md）客户端 —— G1 / P0。
 *
 * 后端已硬编码文件路径，本模块只透传内容；保存失败时把
 * `Backend PUT cmd=... → 422: {"detail":{...}}` 解析成结构化错误，
 * 供设置页内联展示安全扫描拒绝原因。
 */

import { invoke } from './desktopInvoke';

export const GLOBAL_RULES_CHAR_LIMIT = 8000;
export const GLOBAL_RULES_MAX_BYTES = 64 * 1024;

export interface GlobalRulesState {
  content: string;
  path: string;
  exists: boolean;
  size: number;
  mtime: number | null;
  truncated: boolean;
  char_limit: number;
  symlink: boolean;
  read_error?: string;
}

export interface GlobalRulesTemplate {
  id: string;
  name: string;
  content: string;
}

export interface GlobalRulesDeleteResult {
  status: string;
  deleted: boolean;
}

export class GlobalRulesError extends Error {
  /** 后端 detail.type：错误类型码（empty_content / unsafe_content / …） */
  readonly type?: string;
  /** 后端 detail.reason：补充原因（如安全扫描命中的威胁描述） */
  readonly reason?: string;
  readonly status?: number;

  constructor(message: string, status?: number, type?: string, reason?: string) {
    super(message);
    this.name = 'GlobalRulesError';
    this.status = status;
    this.type = type;
    this.reason = reason;
  }
}

const STATUS_RE = /→ (\d+):\s*([\s\S]*)$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function parseErrorPayload(payload: string): {
  message?: string;
  type?: string;
  reason?: string;
} {
  try {
    const parsed: unknown = JSON.parse(payload);
    const detail = isRecord(parsed) ? parsed.detail : undefined;
    if (isRecord(detail)) {
      return {
        message: typeof detail.message === 'string' ? detail.message : undefined,
        type: typeof detail.type === 'string' ? detail.type : undefined,
        reason: typeof detail.reason === 'string' ? detail.reason : undefined,
      };
    }
    if (typeof detail === 'string') {
      return { message: detail };
    }
  } catch {
    // 非 JSON 错误体（网关 HTML 等）— 保留原始 message
  }
  return {};
}

function toGlobalRulesError(err: unknown): GlobalRulesError {
  const raw = err instanceof Error ? err.message : String(err);
  const match = raw.match(STATUS_RE);
  if (!match) return new GlobalRulesError(raw);

  const status = Number(match[1]);
  const { message, type, reason } = parseErrorPayload(match[2].trim());
  return new GlobalRulesError(message ?? raw, status, type, reason);
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(cmd, args);
  } catch (err) {
    throw toGlobalRulesError(err);
  }
}

export function normalizeGlobalRulesState(raw: unknown): GlobalRulesState {
  if (!isRecord(raw)) {
    throw new GlobalRulesError('后端返回的全局规则格式无效');
  }
  const state: GlobalRulesState = {
    content: asString(raw.content),
    path: asString(raw.path),
    exists: raw.exists === true,
    size: asNumber(raw.size, 0),
    mtime: typeof raw.mtime === 'number' ? raw.mtime : null,
    truncated: raw.truncated === true,
    char_limit: asNumber(raw.char_limit, GLOBAL_RULES_CHAR_LIMIT),
    symlink: raw.symlink === true,
  };
  if (typeof raw.read_error === 'string' && raw.read_error) {
    state.read_error = raw.read_error;
  }
  return state;
}

function normalizeTemplates(raw: unknown): GlobalRulesTemplate[] {
  if (!isRecord(raw) || !Array.isArray(raw.templates)) {
    throw new GlobalRulesError('后端返回的模板格式无效');
  }
  return raw.templates.filter(isRecord).map((item) => ({
    id: asString(item.id),
    name: asString(item.name),
    content: asString(item.content),
  }));
}

export const globalRulesApi = {
  async get(): Promise<GlobalRulesState> {
    return normalizeGlobalRulesState(await call<unknown>('global_rules_get'));
  },

  async save(content: string): Promise<GlobalRulesState> {
    return normalizeGlobalRulesState(await call<unknown>('global_rules_save', { content }));
  },

  async remove(): Promise<GlobalRulesDeleteResult> {
    const raw = await call<unknown>('global_rules_delete');
    if (!isRecord(raw)) {
      throw new GlobalRulesError('后端返回的删除结果格式无效');
    }
    return { status: asString(raw.status, 'ok'), deleted: raw.deleted === true };
  },

  async templates(): Promise<GlobalRulesTemplate[]> {
    return normalizeTemplates(await call<unknown>('global_rules_templates'));
  },
};
