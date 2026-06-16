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

export async function invokeBackend(
  cmd: string,
  args: Record<string, unknown> = {},
  backendUrl: string,
): Promise<unknown> {
  const route = COMMAND_ROUTES[cmd];
  if (!route) {
    throw new UnknownIpcCommandError(cmd);
  }
  const url = `${backendUrl}${route.path(args)}`;
  const init: import('node-fetch').RequestInit = {
    method: route.method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    // POST/PUT/PATCH: 把 args 转 snake_case 再序列化(前端 camelCase → 后端 Pydantic)
    const snakeArgs = camelToSnakeKeys(args);
    init.body = JSON.stringify(snakeArgs);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Backend ${route.method} ${url} → ${res.status}: ${text}`);
  }
  return res.json();
}
