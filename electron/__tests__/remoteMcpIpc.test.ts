import { describe, expect, it, vi } from 'vitest';

import { registerRemoteMcpIpc } from '../remoteMcpIpc';
import type { RemoteTunnel } from '../remoteTunnel';

type Handler = (...args: unknown[]) => unknown;

function fakeTunnel(overrides: Partial<Record<keyof RemoteTunnel, unknown>> = {}) {
  let active = false;
  let url: string | null = null;
  const t = {
    start: vi.fn(async () => {
      active = true;
      url = 'https://x-y.trycloudflare.com';
      return url;
    }),
    stop: vi.fn(() => {
      active = false;
      url = null;
    }),
    acknowledgeAddress: vi.fn(),
    snapshot: () => ({
      state: active ? 'running' : 'stopped',
      url,
      error: null,
      health: { state: 'unknown' },
      addressChanged: false,
      retryCount: 0,
    }),
    get isActive() {
      return active;
    },
    get publicUrl() {
      return url;
    },
    ...overrides,
  };
  return t as unknown as RemoteTunnel & { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
}

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function setup(opts: { supported?: boolean; responses?: Record<string, unknown> } = {}) {
  const handlers = new Map<string, Handler>();
  const tunnel = fakeTunnel();
  const clipboard = vi.fn();
  const request = vi.fn(async (url: string, init: { method: string; body?: string }) => {
    const key = `${init.method} ${url.replace('http://b/api/v1/remote-mcp', '')}`;
    const value = opts.responses?.[key];
    if (value instanceof Error) throw value;
    if (value && typeof value === 'object' && 'status' in (value as object)) return value;
    return jsonResponse(200, value ?? {});
  });
  const controller = registerRemoteMcpIpc((c, h) => handlers.set(c, h), {
    tunnel,
    authToken: () => 'tok',
    writeClipboard: clipboard,
    tunnelSupported: opts.supported ?? true,
    hotkeyRegistered: () => true,
    backendUrl: () => 'http://b',
    request: request as never,
  });
  const call = (channel: string, ...args: unknown[]) => handlers.get(channel)!(...args);
  return { handlers, tunnel, clipboard, request, controller, call };
}

const RUNNING = { listener: { running: true, port: 8767 }, paused: false };

describe('remoteMcpIpc', () => {
  it('registers the five channels', () => {
    const { handlers } = setup();
    expect([...handlers.keys()].sort()).toEqual([
      'remote-mcp:copy-url',
      'remote-mcp:emergency-stop',
      'remote-mcp:tunnel-start',
      'remote-mcp:tunnel-state',
      'remote-mcp:tunnel-stop',
    ]);
  });

  it('tunnel-start requires a running, unpaused listener', async () => {
    let s = setup({ responses: { 'GET /state': { listener: { running: false, port: null }, paused: false } } });
    await expect(s.call('remote-mcp:tunnel-start')).rejects.toThrow('请先开启 MCP 监听器');
    s = setup({ responses: { 'GET /state': { ...RUNNING, paused: true } } });
    await expect(s.call('remote-mcp:tunnel-start')).rejects.toThrow('已急停');
    s = setup({ responses: { 'GET /state': RUNNING } });
    const state = (await s.call('remote-mcp:tunnel-start')) as { state: string; hotkeyRegistered: boolean };
    expect(s.tunnel.start).toHaveBeenCalledWith(8767);
    expect(state).toMatchObject({ state: 'running', supported: true, hotkeyRegistered: true });
  });

  it('sends the local auth bearer token', async () => {
    const s = setup({ responses: { 'GET /state': RUNNING } });
    await s.call('remote-mcp:tunnel-start');
    const init = s.request.mock.calls[0][1] as unknown as { headers: Record<string, string> };
    expect(init.headers.Authorization).toBe('Bearer tok');
  });

  it('refuses the tunnel on unsupported (Win7) builds', async () => {
    const s = setup({ supported: false });
    await expect(s.call('remote-mcp:tunnel-start')).rejects.toThrow('不提供公网通道');
    expect(s.request).not.toHaveBeenCalled();
  });

  it('emergency stop stops the tunnel even when the backend fails', async () => {
    const s = setup({ responses: { 'POST /emergency-stop': new Error('ECONNREFUSED') } });
    await expect(s.controller.emergencyStop()).rejects.toThrow('ECONNREFUSED');
    expect(s.tunnel.stop).toHaveBeenCalled();
  });

  it('copy-url writes the clipboard and never returns the url', async () => {
    const s = setup({
      responses: { 'POST /workspaces/ws-1/connection-url': { url: 'http://127.0.0.1:8767/mcp/' + 'a'.repeat(64) } },
    });
    const result = await s.call('remote-mcp:copy-url', { sender: {} }, 'ws-1');
    expect(result).toBe(true);
    expect(s.clipboard).toHaveBeenCalledWith(expect.stringContaining('/mcp/'));
    const body = JSON.parse((s.request.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({ public_base: null });
  });

  it('copy-url public requires a tunnel and passes public_base', async () => {
    const s = setup({
      responses: {
        'GET /state': RUNNING,
        'POST /workspaces/ws-1/connection-url': { url: 'https://x-y.trycloudflare.com/mcp/abc' },
      },
    });
    await expect(s.call('remote-mcp:copy-url', 'ws-1', { public: true })).rejects.toThrow('请先开启公网通道');
    await s.call('remote-mcp:tunnel-start');
    await s.call('remote-mcp:copy-url', 'ws-1', { public: true });
    const last = s.request.mock.calls.at(-1)![1] as { body: string };
    expect(JSON.parse(last.body)).toEqual({ public_base: 'https://x-y.trycloudflare.com' });
    expect(s.tunnel.acknowledgeAddress).toHaveBeenCalled();
  });

  it('copy-url validates arguments', async () => {
    const s = setup();
    await expect(s.call('remote-mcp:copy-url', '../x')).rejects.toThrow('invalid workspace id');
    await expect(s.call('remote-mcp:copy-url', 'ws-1', { plain: true })).rejects.toThrow('invalid options');
  });

  it('surfaces backend detail messages', async () => {
    const s = setup({ responses: { 'GET /state': jsonResponse(403, { detail: 'forbidden-x' }) } });
    await expect(s.call('remote-mcp:tunnel-start')).rejects.toThrow('forbidden-x');
  });
});
