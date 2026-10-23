/**
 * Workspace MCP Server — Electron-side IPC (M4).
 *
 * Spec: docs/plans/2026-09-26-workspace-mcp-m4-ui.md §2.2–2.3
 *
 * Channels (the caller wraps each handler with isTrustedRenderer + demo
 * checks, same as skillsIpc):
 *   remote-mcp:tunnel-state    → tunnel snapshot + supported/hotkey flags
 *   remote-mcp:tunnel-start    → requires backend listener running & not paused
 *   remote-mcp:tunnel-stop
 *   remote-mcp:emergency-stop  → stop tunnel, then POST /remote-mcp/emergency-stop
 *   remote-mcp:copy-url        → backend builds URL, written straight to the
 *                                clipboard; the token never reaches the renderer
 *
 * Pure module: electron's clipboard is injected so this is unit-testable.
 */
import { fetchCompat } from './fetchCompat';
import { RemoteTunnel, type TunnelSnapshot } from './remoteTunnel';

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8765';
const API_PREFIX = '/api/v1/remote-mcp';

export type RegisterIpcHandler = (channel: string, handler: (...args: unknown[]) => unknown) => void;

interface RemoteMcpTunnelState extends TunnelSnapshot {
  supported: boolean;
  hotkeyRegistered: boolean;
}

export interface RemoteMcpIpcDeps {
  tunnel: RemoteTunnel;
  authToken: () => string | undefined;
  writeClipboard: (text: string) => void;
  /** false on the Win7 LTS line — tunnel is not offered there. */
  tunnelSupported: boolean;
  hotkeyRegistered?: () => boolean;
  backendUrl?: () => string;
  request?: typeof fetchCompat;
}

export interface RemoteMcpController {
  emergencyStop(): Promise<void>;
  state(): RemoteMcpTunnelState;
  dispose(): void;
}

interface ListenerState {
  listener?: { running?: boolean; port?: number | null };
  paused?: boolean;
}

function detailMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
    return (detail as { message: string }).message;
  }
  return `HTTP ${status}`;
}

function parseCopyArgs(args: unknown[]): { id: string; usePublic: boolean } {
  // Handlers receive (event, ...args) from ipcMain; tolerate both shapes.
  const rest = args.length && typeof args[0] === 'object' && args[0] !== null && 'sender' in (args[0] as object)
    ? args.slice(1)
    : args;
  const [id, options] = rest;
  if (typeof id !== 'string' || !/^[A-Za-z0-9-]{1,64}$/.test(id)) throw new Error('invalid workspace id');
  if (options !== undefined && (typeof options !== 'object' || options === null)) throw new Error('invalid options');
  const opts = (options ?? {}) as Record<string, unknown>;
  if (Object.keys(opts).some((k) => k !== 'public')) throw new Error('invalid options');
  if ('public' in opts && typeof opts.public !== 'boolean') throw new Error('invalid options');
  return { id, usePublic: opts.public === true };
}

export function registerRemoteMcpIpc(register: RegisterIpcHandler, deps: RemoteMcpIpcDeps): RemoteMcpController {
  const request = deps.request ?? fetchCompat;
  const baseUrl = deps.backendUrl ?? (() => process.env.PYTHON_BACKEND_URL || DEFAULT_BACKEND_URL);
  const { tunnel } = deps;

  async function backend(method: 'GET' | 'POST', path: string, body?: unknown): Promise<unknown> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const token = deps.authToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await request(`${baseUrl()}${API_PREFIX}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      /* empty body */
    }
    if (!response.ok) throw new Error(detailMessage(data, response.status));
    return data;
  }

  function state(): RemoteMcpTunnelState {
    return {
      ...tunnel.snapshot(),
      supported: deps.tunnelSupported,
      hotkeyRegistered: deps.hotkeyRegistered?.() ?? false,
    };
  }

  async function emergencyStop(): Promise<void> {
    // Tunnel first: even if the backend is unreachable, public access ends.
    tunnel.stop();
    await backend('POST', '/emergency-stop');
  }

  register('remote-mcp:tunnel-state', () => state());

  register('remote-mcp:tunnel-start', async () => {
    if (!deps.tunnelSupported) throw new Error('当前系统版本不提供公网通道，仅支持本机回环访问');
    const current = (await backend('GET', '/state')) as ListenerState;
    if (current.paused) throw new Error('已急停，请先恢复服务');
    const port = current.listener?.port;
    if (!current.listener?.running || typeof port !== 'number') throw new Error('请先开启 MCP 监听器');
    // A startup failure is reflected in state(); don't reject the IPC call
    // with an opaque "Tunnel stopped" when the user cancels mid-start.
    try {
      await tunnel.start(port);
    } catch (err) {
      if (!tunnel.isActive) throw err;
    }
    return state();
  });

  register('remote-mcp:tunnel-stop', () => {
    tunnel.stop();
    return state();
  });

  register('remote-mcp:emergency-stop', async () => {
    await emergencyStop();
    return state();
  });

  register('remote-mcp:copy-url', async (...args: unknown[]) => {
    const { id, usePublic } = parseCopyArgs(args);
    let publicBase: string | undefined;
    if (usePublic) {
      publicBase = tunnel.publicUrl ?? undefined;
      if (!publicBase) throw new Error('请先开启公网通道');
    }
    const data = (await backend('POST', `/workspaces/${encodeURIComponent(id)}/connection-url`, {
      public_base: publicBase ?? null,
    })) as { url?: unknown };
    if (typeof data?.url !== 'string') throw new Error('后端未返回连接地址');
    deps.writeClipboard(data.url);
    if (usePublic) tunnel.acknowledgeAddress();
    return true; // never echo the URL (it embeds the token)
  });

  return {
    emergencyStop,
    state,
    dispose: () => tunnel.stop(),
  };
}
