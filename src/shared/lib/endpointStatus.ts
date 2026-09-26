/**
 * 对话阅读体验 C3（docs/mcp-chat-reading-nav-optimization.md §10.6）：云端模型端点
 * 可达性状态。
 *
 * chatApi 在流式失败时按错误类型上报：`network_error`、`timeout`，或 `server_error`
 * 且状态码为 502 / 503 / 504，记为「端点不可达」；之后任意一次流式成功完成即清除。
 * 不做后台定时探测，避免空耗请求。
 */
import { create } from 'zustand';

export type EndpointIssueKind = 'network' | 'timeout' | 'server';

export interface EndpointIssue {
  kind: EndpointIssueKind;
  /** 出错请求所用端点的 baseUrl（用于和当前选中的端点比对） */
  baseUrl: string | null;
  host: string | null;
  model: string | null;
  status: number | null;
  message: string;
  at: number;
}

interface EndpointStatusState {
  issue: EndpointIssue | null;
  /** 用户已关闭当前提示；下一次新的失败会重新显示 */
  dismissed: boolean;
  report: (issue: EndpointIssue) => void;
  clear: () => void;
  dismiss: () => void;
}

export const useEndpointStatusStore = create<EndpointStatusState>((set) => ({
  issue: null,
  dismissed: false,
  report: (issue) => set({ issue, dismissed: false }),
  clear: () => set({ issue: null, dismissed: false }),
  dismiss: () => set({ dismissed: true }),
}));

const UNAVAILABLE_STATUS = new Set([502, 503, 504]);

type Classified = Pick<EndpointIssue, 'kind' | 'status' | 'message'>;

/** 把失败事件的 error 信封（`LLMError.to_dict()`）归类；不属于「端点不可达」时返回 null。 */
export function classifyEndpointError(error: unknown): Classified | null {
  if (!error || typeof error !== 'object') return null;
  const { type, status_code: statusCode, message } = error as Record<string, unknown>;
  const status = typeof statusCode === 'number' ? statusCode : null;
  const text = typeof message === 'string' ? message : '';
  if (type === 'network_error') return { kind: 'network', status, message: text };
  if (type === 'timeout') return { kind: 'timeout', status, message: text };
  if (type === 'server_error' && status != null && UNAVAILABLE_STATUS.has(status)) {
    return { kind: 'server', status, message: text };
  }
  return null;
}

export function hostOf(baseUrl: string | null | undefined): string | null {
  if (!baseUrl) return null;
  try {
    return new URL(baseUrl).host || null;
  } catch {
    return null;
  }
}

/** 两个 baseUrl 是否指向同一端点（忽略末尾斜杠与大小写）。 */
export function isSameEndpoint(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  const norm = (url: string) => url.trim().replace(/\/+$/, '').toLowerCase();
  return Boolean(a && b) && norm(a as string) === norm(b as string);
}

/** chatApi：流式以 failed 收尾时调用。 */
export function reportStreamFailure(
  error: unknown,
  config?: { apiUrl?: string; model?: string },
): void {
  const classified = classifyEndpointError(error);
  if (!classified) return;
  useEndpointStatusStore.getState().report({
    ...classified,
    baseUrl: config?.apiUrl ?? null,
    host: hostOf(config?.apiUrl),
    model: config?.model ?? null,
    at: Date.now(),
  });
}

/** chatApi：流式正常完成时调用。 */
export function reportStreamSuccess(): void {
  if (useEndpointStatusStore.getState().issue) useEndpointStatusStore.getState().clear();
}
