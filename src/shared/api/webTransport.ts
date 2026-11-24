/**
 * Browser transport for web fallback mode (backend launched with SAGE_WEB_MODE=1).
 *
 * In Electron the renderer reaches the local backend through the preload bridge
 * (window.electronAPI → main process → FastAPI). A plain browser has no bridge,
 * so historically the SPA loaded but every API call failed closed — the web
 * launcher (SageWeb.cmd) opened a page that could not talk to the backend at
 * all. This module re-implements the three bridge operations over same-origin
 * HTTP:
 *
 *   invoke(cmd, args)        → COMMAND_ROUTES lookup → REST call
 *   backendRequest(request)  → direct fetch to an explicit REST path
 *   listen(event, handler)   → NDJSON relay for chat-stream-* / shell-stream-*
 *
 * Route resolution reuses `electron/commands.ts`, which is deliberately a pure
 * module (relative imports only) — see its header comment. Keeping one source
 * of truth here means a new IPC command works in web mode without a second
 * mapping table to maintain.
 *
 * Authentication: backend.cli.web mints SAGE_LOCAL_AUTH_TOKEN and hands it to
 * the browser via `?token=…`; the inline bootstrap in index.html persists it
 * to localStorage['sage_auth_token'] and strips it from the URL. `invoke()`
 * carries it as `Authorization: Bearer …`; `backendRequest()` carries it as
 * `X-Sage-Local-Authorization` so a caller-supplied `Authorization` (e.g. the
 * upstream provider API key routed through the LLM proxy) is not overwritten
 * — matching the Electron main process relay (`electron/main.ts`
 * `sage:backend-request`) semantics.
 */
import { COMMAND_ROUTES } from '../../../electron/commands';

import {
  getWebAuthHeaders,
  getWebAuthToken,
  getWebCapabilityHeaders,
  isBrowserRuntime,
} from './webAuth';

// 凭据读取拆到 webAuth.ts（见该文件头注释：桌面端产物不应打包整张
// IPC 路由表）。这里 re-export 保持既有 import 路径可用。
export { getWebAuthHeaders, getWebAuthToken, getWebCapabilityHeaders, isBrowserRuntime };
/** Thrown for Electron-only channels (pty, window management, …) in a browser. */
export class WebDesktopOnlyError extends Error {
  readonly code = 'WEB_DESKTOP_ONLY';

  constructor(cmd: string) {
    super(`「${cmd}」仅在 Sage 桌面端可用（网页模式不支持此功能）`);
    this.name = 'WebDesktopOnlyError';
  }
}

/**
 * Mirror of electron/invoke.ts camelToSnakeKeys: the renderer speaks camelCase,
 * FastAPI Pydantic models are snake_case. Query strings built by route.path()
 * are already snake_case and must not go through this.
 */
function camelToSnakeKeys(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => camelToSnakeKeys(item));
  }
  if (
    value !== null &&
    typeof value === 'object' &&
    Object.getPrototypeOf(value) === Object.prototype
  ) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const snake = k.replace(/([A-Z])/g, (_, c: string) => '_' + c.toLowerCase());
      out[snake] = camelToSnakeKeys(v);
    }
    return out;
  }
  return value;
}

interface HttpErrorLike extends Error {
  status_code?: number;
}

function backendUnavailable(error: unknown): Error {
  const detail = error instanceof Error ? error.message : String(error);
  return new Error(`后端服务未启动或已断开：${detail}`);
}

/** Build an Error carrying status_code (desktopInvoke's funnel reads it). */
function httpError(status: number, body: string): HttpErrorLike {
  let message = '';
  try {
    const parsed = JSON.parse(body) as { detail?: unknown; message?: unknown };
    if (typeof parsed.detail === 'string') {
      message = parsed.detail;
    } else if (parsed.detail && typeof parsed.detail === 'object') {
      const detail = parsed.detail as { message?: unknown };
      if (typeof detail.message === 'string') message = detail.message;
    } else if (typeof parsed.message === 'string') {
      message = parsed.message;
    }
  } catch {
    // Non-JSON error body — keep the generic text.
  }
  const err = new Error(`${message || '请求失败'}（HTTP ${status}）`) as HttpErrorLike;
  err.status_code = status;
  return err;
}

async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw backendUnavailable(error);
  }
}

// ── invoke() ────────────────────────────────────────────────────────────────

/**
 * Browser counterpart of electron/invoke.ts::invokeBackend. Unknown commands
 * are Electron-only channels; callers surface the WebDesktopOnlyError message.
 */
export async function invokeViaHttp<T>(
  cmd: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  const route = COMMAND_ROUTES[cmd];
  if (!route) throw new WebDesktopOnlyError(cmd);

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getWebAuthHeaders(),
  };
  const init: RequestInit = { method: route.method, headers };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    const bodyArgs = route.body?.(args) ?? args;
    init.body = JSON.stringify(route.rawBody ? bodyArgs : camelToSnakeKeys(bodyArgs));
  }

  const response = await fetchOrThrow(route.path(args), init);
  if (!response.ok) {
    throw httpError(response.status, await response.text().catch(() => ''));
  }
  if (response.status === 204) return null as T;
  const text = await response.text();
  if (!text) return null as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as unknown as T;
  }
}

// ── backendRequest() ────────────────────────────────────────────────────────

/**
 * Browser counterpart of electron main's `sage:backend-request` relay: an
 * explicit REST call with the capability header. Supports the same response
 * types (json / text / arraybuffer) and bounded timeout.
 */
export async function backendRequestViaHttp<T>(request: {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  headers?: HeadersInit;
  body?: unknown;
  timeoutMs?: number;
  responseType?: 'json' | 'arraybuffer' | 'text';
}): Promise<T> {
  const method = request.method ?? 'GET';
  const controller = request.timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), request.timeoutMs) : null;

  // 用 Headers 对象做合并：同名 header 自动按 name-insensitive 合并，避免调用方
  // 提供 `Authorization` 时与本地能力 header 产生大小写两份 → 浏览器最后发送哪一
  // 份由插入顺序决定、难以预测。Electron 主进程的中继 (`electron/main.ts`
  // `sage:backend-request`) 同样使用 `X-Sage-Local-Authorization` 承载本地能力，
  // 让上游 API Key 走 `Authorization`，此处镜像相同语义。
  const headers = new Headers(getWebCapabilityHeaders());
  if (request.body !== undefined) headers.set('Content-Type', 'application/json');
  const extra = request.headers;
  if (extra) {
    new Headers(extra).forEach((value, key) => {
      headers.set(key, value);
    });
  }

  let response: Response;
  try {
    response = await fetch(request.path, {
      method,
      headers,
      body:
        request.body === undefined
          ? undefined
          : typeof request.body === 'string'
            ? request.body
            : JSON.stringify(request.body),
      signal: controller?.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`请求超时（${request.timeoutMs}ms）`);
    }
    throw backendUnavailable(error);
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!response.ok) {
    throw httpError(response.status, await response.text().catch(() => ''));
  }
  if (response.status === 204) return null as T;
  if (request.responseType === 'arraybuffer') return (await response.arrayBuffer()) as T;
  if (request.responseType === 'text') return (await response.text()) as T;
  const text = await response.text();
  if (!text) return null as T;
  return JSON.parse(text) as T;
}

// ── listen() ────────────────────────────────────────────────────────────────

const CHAT_STREAM_EVENT = /^chat-stream-(.+)$/;
const SHELL_STREAM_EVENT = /^shell-stream-(.+)$/;

/**
 * Relay an NDJSON endpoint, invoking `emit` with each parsed line. Errors and
 * aborts are silent — subscribers treat a dead stream the same way the IPC
 * relay does (no further events, the client watchdog takes over).
 */
async function relayNdjson(
  url: string,
  signal: AbortSignal,
  emit: (payload: unknown) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/x-ndjson', ...getWebAuthHeaders() },
      signal,
    });
  } catch {
    return;
  }
  if (!response.ok || !response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf('\n');
      while (newline >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) {
          try {
            emit(JSON.parse(line));
          } catch {
            // Malformed line — skip, matching the main-process parser.
          }
        }
        newline = buffer.indexOf('\n');
      }
    }
  } catch {
    // AbortError or transport failure: stop silently (same as the IPC relay).
  }
}

/**
 * Browser counterpart of the `sage:listen` relay. Only backend-backed dynamic
 * streams have a transport here; app-lifecycle events (backend:ready,
 * session-notify-click, …) are produced by the Electron main process and are
 * simply inert in a browser.
 */
export async function listenViaHttp<T>(
  event: string,
  handler: (event: { payload: T }) => void,
): Promise<() => void> {
  const chatMatch = CHAT_STREAM_EVENT.exec(event);
  const shellMatch = SHELL_STREAM_EVENT.exec(event);
  if (!chatMatch && !shellMatch) return () => {};

  const url = chatMatch
    ? `/api/v1/chat/stream/${encodeURIComponent(chatMatch[1])}`
    : `/api/v1/shells/${encodeURIComponent(shellMatch![1])}/stream`;
  const controller = new AbortController();
  void relayNdjson(url, controller.signal, (payload) => handler({ payload: payload as T }));
  return () => controller.abort();
}
