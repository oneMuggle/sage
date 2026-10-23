import { EventEmitter } from 'events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RemoteTunnel, type FetchFn, type SpawnFn, type TunnelChild } from '../remoteTunnel';

class FakeChild extends EventEmitter implements TunnelChild {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  killed = false;
  kill(): void {
    this.killed = true;
  }
  say(text: string): void {
    this.stderr.emit('data', Buffer.from(text));
  }
}

function setup(opts: { fetch?: FetchFn } = {}) {
  const children: FakeChild[] = [];
  const calls: Array<{ command: string; args: string[] }> = [];
  const spawn: SpawnFn = (command, args) => {
    const child = new FakeChild();
    children.push(child);
    calls.push({ command, args });
    return child;
  };
  const tunnel = new RemoteTunnel({
    spawn,
    fetch: opts.fetch,
    exists: () => false,
    platform: 'win32',
    env: {},
    startTimeoutMs: 1000,
    healthIntervalMs: opts.fetch ? 15000 : 0,
    retryDelays: [10, 20],
  });
  return { tunnel, children, calls };
}

const READY = 'INF |  https://abc-def-ghi.trycloudflare.com  |\nINF Registered tunnel connection connIndex=0\n';

describe('RemoteTunnel', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('spawns cloudflared against the loopback listener and resolves when registered', async () => {
    const { tunnel, children, calls } = setup();
    const started = tunnel.start(8767);
    expect(calls[0].command).toBe('cloudflared');
    expect(calls[0].args).toEqual(['tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8767']);
    expect(tunnel.snapshot().state).toBe('starting');
    children[0].say('INF Requesting new quick Tunnel on trycloudflare.com...\n');
    children[0].say('https://api.trycloudflare.com/tunnel\n');
    children[0].say(READY);
    await expect(started).resolves.toBe('https://abc-def-ghi.trycloudflare.com');
    expect(tunnel.snapshot()).toMatchObject({ state: 'running', url: 'https://abc-def-ghi.trycloudflare.com' });
  });

  it('does not treat the host as ready before registration', async () => {
    const { tunnel, children } = setup();
    void tunnel.start(8767).catch(() => undefined);
    children[0].say('https://abc.trycloudflare.com\n');
    expect(tunnel.snapshot().state).toBe('starting');
    expect(tunnel.publicUrl).toBeNull();
    tunnel.stop();
  });

  it('rejects duplicate start and invalid ports', async () => {
    const { tunnel } = setup();
    await expect(tunnel.start(80)).rejects.toThrow('invalid listener port');
    void tunnel.start(8767).catch(() => undefined);
    await expect(tunnel.start(8767)).rejects.toThrow('请勿重复启动');
    tunnel.stop();
  });

  it('times out startup and schedules a retry', async () => {
    const { tunnel, children } = setup();
    const started = tunnel.start(8767);
    vi.advanceTimersByTime(1000);
    await expect(started).rejects.toThrow('timed out');
    expect(children[0].killed).toBe(true);
    expect(tunnel.snapshot().state).toBe('reconnecting');
    vi.advanceTimersByTime(10);
    expect(children).toHaveLength(2);
    tunnel.stop();
  });

  it('treats ENOENT as fatal (no retry)', async () => {
    const { tunnel, children } = setup();
    const started = tunnel.start(8767);
    const err = Object.assign(new Error('spawn cloudflared ENOENT'), { code: 'ENOENT' });
    children[0].emit('error', err);
    await expect(started).rejects.toThrow('cloudflared: ENOENT');
    vi.advanceTimersByTime(100);
    expect(children).toHaveLength(1);
    expect(tunnel.snapshot().state).toBe('error');
    expect(tunnel.isActive).toBe(false);
  });

  it('reconnects after an unexpected exit and flags an address change', async () => {
    const { tunnel, children } = setup();
    const started = tunnel.start(8767);
    children[0].say(READY);
    await started;
    children[0].emit('close', 1);
    expect(tunnel.snapshot().state).toBe('reconnecting');
    expect(tunnel.publicUrl).toBeNull();
    vi.advanceTimersByTime(10);
    children[1].say('https://new-host.trycloudflare.com\nRegistered tunnel connection\n');
    expect(tunnel.snapshot()).toMatchObject({
      state: 'running',
      url: 'https://new-host.trycloudflare.com',
      addressChanged: true,
    });
    tunnel.acknowledgeAddress();
    expect(tunnel.snapshot().addressChanged).toBe(false);
    tunnel.stop();
  });

  it('stop is idempotent and kills the child without retry', async () => {
    const { tunnel, children } = setup();
    const started = tunnel.start(8767);
    tunnel.stop();
    await expect(started).rejects.toThrow('Tunnel stopped');
    expect(children[0].killed).toBe(true);
    children[0].emit('close', null);
    vi.advanceTimersByTime(100);
    expect(children).toHaveLength(1);
    tunnel.stop();
    expect(tunnel.snapshot()).toMatchObject({ state: 'stopped', url: null });
  });

  it('prefers cloudflared under Program Files when present', () => {
    const tunnel = new RemoteTunnel({
      platform: 'win32',
      env: { ProgramFiles: 'C:\\PF' },
      exists: (p) => p.includes('PF'),
    });
    expect(tunnel.executable()).toMatch(/PF.cloudflared.cloudflared\.exe$/);
  });
});

describe('RemoteTunnel health probe', () => {
  it('marks healthy on matching service and degraded (keeping the url) on failure', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ service: 'SageWorkspaceMCP' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ service: 'Other' }) });
    const { tunnel, children } = setup({ fetch });
    const started = tunnel.start(8767);
    children[0].say(READY);
    await started;
    await Promise.resolve();
    await tunnel.probe(); // first probe may still be running; ensure one completes
    await new Promise((r) => setTimeout(r, 0));
    const url = tunnel.publicUrl;
    expect(url).toBe('https://abc-def-ghi.trycloudflare.com');
    await tunnel.probe();
    expect(tunnel.snapshot().state).toBe('degraded');
    expect(tunnel.snapshot().health.state).toBe('unreachable');
    expect(tunnel.publicUrl).toBe(url);
    expect(fetch).toHaveBeenCalledWith(`${url}/healthz`, expect.objectContaining({ redirect: 'error' }));
    tunnel.stop();
  });
});
