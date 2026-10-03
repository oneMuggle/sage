/**
 * UI -> bridge -> HTTP wire harness.
 *
 * The renderer tests stub `invoke`, the electron tests check the route table's shape, the backend
 * tests call routes directly — nothing checked that a click in the UI ends up as the HTTP request
 * the backend expects. This harness closes that gap without a browser or an Electron process:
 *
 *   React component -> src/shared/api/* -> window.electronAPI.invoke
 *     -> the REAL electron/invoke.ts (COMMAND_ROUTES, camelCase->snake_case, body mappers)
 *     -> a fake backend behind the mocked `node-fetch`
 *
 * Keep this file free of React / src imports: tsconfig.electron.json type-checks every .ts under
 * electron/. Test files that render components are .test.tsx (not part of that program).
 */
import { invokeBackend } from '../../invoke';
import { wireFetch } from './fetchStub';

const BACKEND = 'http://127.0.0.1:8765';

export interface WireRequest {
  method: string;
  path: string;
  query: string;
  body: unknown;
}
export interface WireReply {
  status?: number;
  json?: unknown;
}
export interface WireRoute {
  method: string;
  path: string | RegExp;
  reply: (req: WireRequest, match: RegExpMatchArray) => WireReply;
}

/** Every request the fake backend received, in order. */
const requests: WireRequest[] = [];

type WithBridge = typeof globalThis & { electronAPI?: unknown };

function respond({ status = 200, json = {} }: WireReply) {
  return {
    ok: status < 400,
    status,
    json: async () => json,
    text: async () => JSON.stringify(json),
  };
}

/** Install the fake backend and a `window.electronAPI.invoke` that goes through the real bridge. */
export function useBackend(routes: WireRoute[]): void {
  requests.length = 0;
  wireFetch.mockReset();
  wireFetch.mockImplementation(async (url: string, init?: { method?: string; body?: string }) => {
    const u = new URL(url);
    const req: WireRequest = {
      method: init?.method ?? 'GET',
      path: u.pathname,
      query: u.search,
      body: init?.body === undefined ? undefined : JSON.parse(init.body),
    };
    requests.push(req);
    for (const route of routes) {
      if (route.method !== req.method) continue;
      const match =
        typeof route.path === 'string'
          ? route.path === req.path
            ? ([req.path] as RegExpMatchArray)
            : null
          : req.path.match(route.path);
      if (match) return respond(route.reply(req, match));
    }
    return respond({
      status: 404,
      json: { detail: `no fake backend route for ${req.method} ${req.path}` },
    });
  });
  (globalThis as WithBridge).electronAPI = {
    invoke: (cmd: string, args?: Record<string, unknown>) =>
      invokeBackend(cmd, args ?? {}, BACKEND),
  };
}

export function releaseBackend(): void {
  delete (globalThis as WithBridge).electronAPI;
  wireFetch.mockReset();
  requests.length = 0;
}

/** The requests the fake backend received for one route. */
export const received = (method: string, path: string | RegExp): WireRequest[] =>
  requests.filter(
    (r) => r.method === method && (typeof path === 'string' ? r.path === path : path.test(r.path)),
  );

/**
 * Mirrors a backend request model with `extra="forbid"`: unknown body keys are a 422, exactly what
 * FastAPI answers. A mapping that leaks `projectId` or a UI-only field fails the test the way it
 * would fail in the app.
 */
export function strictBody(
  allowed: readonly string[],
  reply: (body: Record<string, unknown>, req: WireRequest, match: RegExpMatchArray) => WireReply,
): WireRoute['reply'] {
  return (req, match) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const extra = Object.keys(body).filter((k) => !allowed.includes(k));
    if (extra.length > 0) {
      return {
        status: 422,
        json: { detail: `Extra inputs are not permitted: ${extra.join(', ')}` },
      };
    }
    return reply(body, req, match);
  };
}
