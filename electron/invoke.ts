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
 */
import fetch from 'node-fetch';
import { COMMAND_ROUTES, UnknownIpcCommandError } from './commands';

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
    init.body = JSON.stringify(args);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Backend ${route.method} ${url} → ${res.status}: ${text}`);
  }
  return res.json();
}
