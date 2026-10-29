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
      const snake = k.replace(/([A-Z])/g, (_, c) => '_' + c.toLowerCase());
      out[snake] = camelToSnakeKeys(v);
    }
    return out;
  }
  return value;
}

/**
 * 2026-10-29: 从后端错误响应体中提取可读文案与错误码。
 *
 * FastAPI 的 HTTPException(detail={"code","message"}) 此前被整段 JSON 拼进
 * IPC 错误消息，renderer 无法按 code 分支、用户只能看到原始信封。
 * 解析失败时返回空对象，调用方回退到「cmd + status + 原文」格式。
 */
function parseBackendErrorDetail(text: string): { message?: string; code?: string } {
  try {
    const body = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
    };
    const detail = body?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return { message: detail };
    }
    if (detail && typeof detail === 'object') {
      const record = detail as { code?: unknown; message?: unknown };
      return {
        message: typeof record.message === 'string' ? record.message : undefined,
        code: typeof record.code === 'string' ? record.code : undefined,
      };
    }
    if (typeof body?.message === 'string' && body.message.trim()) {
      return { message: body.message };
    }
  } catch {
    // 非 JSON 响应体（纯文本/HTML）—— 保持原来的可读错误格式
  }
  return {};
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
  const url = `${backendUrl}${route.path(args)}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  const init: import('node-fetch').RequestInit = {
    method: route.method,
    headers,
  };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    // POST/PUT/PATCH: 把 args 转 snake_case 再序列化(前端 camelCase → 后端 Pydantic)
    // rawBody 路由跳过转换 — 载荷 key 是用户数据(如 MCP env 变量名)而非 JS 标识符
    const bodyArgs = route.body?.(args) ?? args;
    init.body = JSON.stringify(route.rawBody ? bodyArgs : camelToSnakeKeys(bodyArgs));
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    // 安全错误信息:不把完整 URL 拼入异常,避免用户查询等敏感 path 参数
    // 泄漏到主进程日志。用 cmd 作为标识,运维可根据 cmd 反查路由。
    // 2026-10-29: 后端 detail.message 可直接读时优先使用（例如「当前会话
    // 尚未绑定工作区」），同时保留 ``（HTTP <status>）`` 标记 —— renderer
    // 的 desktopInvoke 依赖该标记恢复 status_code（IPC 会剥离自定义属性）。
    const detail = parseBackendErrorDetail(text);
    const err = new Error(
      detail.message
        ? `${detail.message}（HTTP ${res.status}）`
        : `Backend ${route.method} cmd=${cmd} → ${res.status}: ${text}`,
    ) as Error & {
      status_code?: number;
      code?: string;
    };
    // §13.7: 附加状态码（进程内契约；main 进程 sage:invoke 会用 new Error(msg)
    // 重包装剥掉自定义属性，renderer 侧由 desktopInvoke 从 message 解析兜底）。
    err.status_code = res.status;
    if (detail.code) err.code = detail.code;
    throw err;
  }
  return res.json();
}
