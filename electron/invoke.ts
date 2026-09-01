/**
 * IPC invoke → backend HTTP forwarder.
 *
 * Extracted from electron/main.ts so it can be unit-tested without
 * spinning up the Electron runtime (and the Node 16 quirks that come
 * with it — no global `fetch`).
 *
 * Why node-fetch instead of global `fetch`?
 *   Electron 21.4.4 bundles Node 16.13.1, which does NOT expose a global
 *   `fetch` (that landed in Node 18). Tests run on the host Node (>=18),
 *   which DOES have global fetch, so a `vi.stubGlobal('fetch', mock)`
 *   would silently mask the runtime bug. Importing `node-fetch` makes
 *   the dependency explicit and lets tests mock the module import.
 *
 * Why camelToSnakeKeys?
 *   前端 (src/) 用 JS 习惯的 camelCase (sessionId / apiKey / maxContext),
 *   后端 FastAPI Pydantic 用 Python 习惯的 snake_case (session_id /
 *   api_key / max_context)。Bridge 在这里翻译,后端保持 idiomatic Python,
 *   前端保持 idiomatic JS — 各守各的 idiom。
 *   Query string args 不会被转换(它们已经在 path builder 里按 snake 用了)。
 */
import fetch from 'node-fetch';
import { COMMAND_ROUTES, UnknownIpcCommandError } from './commands';

/**
 * Thrown by the IPC handler when an `invoke()` arrives before the backend
 * has passed its health-ownership probe (i.e. lifecycle === 'ready').
 *
 * Renderer contract (Task 0 review round 1, finding #6):
 *   - `code === 'BACKEND_NOT_READY'` is the stable signal.
 *   - `message` is human-readable Chinese — desktopInvoke.ts forwards it
 *     verbatim, BackendStatusBanner doesn't need to render it (it listens
 *     to the 'backend:disconnected' event for the auto-reconnecting banner).
 *
 * Why a typed error (not a generic Error):
 *   Renderer distinguishes "backend offline → show reconnect banner" from
 *   "endpoint said 4xx/5xx → show the server's message verbatim". A
 *   generic Error with the same message conflated the two and previously
 *   caused a "后端服务未启动或已断开" toast to appear over a real 422
 *   (Pydantic validation) error.
 */
export class BackendNotReadyError extends Error {
  readonly code = 'BACKEND_NOT_READY';
  constructor(message = '后端服务尚未就绪,请稍候或重启 Sage') {
    super(message);
    this.name = 'BackendNotReadyError';
  }
}

/**
 * 把对象里所有 camelCase key 转成 snake_case,递归处理嵌套对象和数组里的对象元素。
 * - 单段 key ("title", "id") 不动
 * - 已含下划线 ("max_iterations") 不动
 * - 数组里 string 元素不动(只递归对象元素)
 * - null / undefined / 非 plain object 直接返回
 */
export function camelToSnakeKeys(value: unknown): unknown {
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
      const snake = k.replace(/([A-Z])/g, (_, c) => '_' + c.toLowerCase());
      out[snake] = camelToSnakeKeys(v);
    }
    return out;
  }
  return value;
}

/**
 * Extract `{name}` placeholders from a route template path. Used by
 * invokeBackend to substitute path params from args and strip them
 * from the request body so they don't get sent twice.
 *
 * Example: `extractPathParams('/api/v1/memory/by-turn/{turn_id}', { turn_id: 't1' })`
 *   → `{ turn_id: 't1' }`
 *
 * Only top-level keys matching template placeholders are returned;
 * missing placeholders are silently skipped (the backend will 404 for
 * malformed paths, which surfaces as a clear failure to the renderer).
 */
function extractPathParams(
  route: string,
  args: Record<string, unknown>,
): Record<string, string> {
  const matches = route.match(/\{(\w+)\}/g) || [];
  const result: Record<string, string> = {};
  for (const m of matches) {
    const key = m.slice(1, -1);
    if (key in args) {
      const v = args[key];
      if (v !== null && v !== undefined) result[key] = String(v);
    }
  }
  return result;
}

export async function invokeBackend(
  cmd: string,
  args: Record<string, unknown> = {},
  backendUrl: string,
  authToken?: string,
): Promise<unknown> {
  const route = COMMAND_ROUTES[cmd];
  if (!route) {
    throw new UnknownIpcCommandError(cmd);
  }
  // Build the path template, then substitute {name} placeholders from
  // args (Gap D: memory_find_by_turn / memory_get_summary use
  // {turn_id}/{session_id}). Mutating a local copy keeps the caller's
  // args object untouched (immutability rule).
  let path = route.path(args);
  const pathParams = extractPathParams(path, args);
  for (const [k, v] of Object.entries(pathParams)) {
    path = path.replace(`{${k}}`, encodeURIComponent(v));
  }
  const url = `${backendUrl}${path}`;
  // Strip path params from the body so they are not sent twice
  // (once in the URL, once in the JSON body).
  const bodyArgs: Record<string, unknown> = { ...args };
  for (const k of Object.keys(pathParams)) delete bodyArgs[k];
  const init: import('node-fetch').RequestInit = {
    method: route.method,
    headers: {
      'Content-Type': 'application/json',
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
  };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    // POST/PUT/PATCH: 把 args 转 snake_case 再序列化(前端 camelCase → 后端 Pydantic)
    // rawBody 路由跳过转换 — 载荷 key 是用户数据(如 MCP env 变量名)而非 JS 标识符
    const routeBody = route.body?.(bodyArgs) ?? bodyArgs;
    init.body = JSON.stringify(route.rawBody ? routeBody : camelToSnakeKeys(routeBody));
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const err = new Error(`Backend ${route.method} ${url} → ${res.status}: ${text}`) as Error & {
      status_code?: number;
    };
    // §13.7: 附加状态码（进程内契约；main 进程 sage:invoke 会用 new Error(msg)
    // 重包装剥掉自定义属性，renderer 侧由 desktopInvoke 从 message 解析兜底）。
    err.status_code = res.status;
    throw err;
  }
  return res.json();
}
