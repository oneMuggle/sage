/**
 * Cloudflare Quick Tunnel manager for the Workspace MCP Server (M4).
 *
 * Port of reference/LocalBridge-Share/LocalBridge/src/tunnel.cjs.
 * Spec: docs/plans/2026-09-26-workspace-mcp-m4-ui.md §2.1
 *
 * - Spawns `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:<port>`.
 * - Ready only after both a `https://*.trycloudflare.com` host and
 *   "Registered tunnel connection" have appeared (90 s startup timeout).
 * - Unexpected exits reconnect with 1/2/5/10/30 s backoff; ENOENT is fatal.
 * - Health probe every 15 s against `<url>/healthz`; failures only mark the
 *   tunnel `degraded` and never rotate the address.
 *
 * Pure module (no electron imports) — spawn / fetch / exists are injectable
 * for unit tests. Node 16 compatible (no AbortSignal.timeout).
 */
import { spawn as nodeSpawn } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';

export type TunnelState =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'degraded'
  | 'reconnecting'
  | 'error';

export interface TunnelHealth {
  state: 'unknown' | 'checking' | 'healthy' | 'unreachable' | 'stopped';
  latencyMs?: number;
  checkedAt?: string;
  failures?: number;
  reason?: string;
}

export interface TunnelSnapshot {
  state: TunnelState;
  url: string | null;
  error: string | null;
  health: TunnelHealth;
  addressChanged: boolean;
  retryCount: number;
}

/** Minimal child-process surface we rely on (keeps tests simple). */
export interface TunnelChild {
  stdout: { on(event: 'data', cb: (chunk: Buffer | string) => void): unknown } | null;
  stderr: { on(event: 'data', cb: (chunk: Buffer | string) => void): unknown } | null;
  on(event: 'error', cb: (err: NodeJS.ErrnoException) => void): unknown;
  on(event: 'close', cb: (code: number | null) => void): unknown;
  kill(): unknown;
}

export type SpawnFn = (command: string, args: string[], options: Record<string, unknown>) => TunnelChild;

interface HealthResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type FetchFn = (url: string, init: { signal: AbortSignal; redirect: 'error' }) => Promise<HealthResponse>;

export type TunnelLog = (event: string, details?: Record<string, unknown>) => void;

export interface RemoteTunnelOptions {
  spawn?: SpawnFn;
  fetch?: FetchFn;
  exists?: (path: string) => boolean;
  platform?: NodeJS.Platform;
  env?: Record<string, string | undefined>;
  startTimeoutMs?: number;
  healthIntervalMs?: number;
  healthTimeoutMs?: number;
  retryDelays?: number[];
  log?: TunnelLog;
}

const HEALTH_SERVICE_NAME = 'SageWorkspaceMCP';
const HOST_RE = /https:\/\/[a-z0-9-]+\.trycloudflare\.com/gi;
const REGISTERED_RE = /Registered tunnel connection/i;
const OUTPUT_TAIL_CHARS = 12000;

export class RemoteTunnel {
  private readonly spawnFn: SpawnFn;
  private readonly fetchFn: FetchFn | null;
  private readonly exists: (path: string) => boolean;
  private readonly platform: NodeJS.Platform;
  private readonly env: Record<string, string | undefined>;
  private readonly startTimeoutMs: number;
  private readonly healthIntervalMs: number;
  private readonly healthTimeoutMs: number;
  private readonly retryDelays: number[];
  private readonly log: TunnelLog;

  private child: TunnelChild | null = null;
  private url: string | null = null;
  private lastUrl: string | null = null;
  private addressChanged = false;
  private state: TunnelState = 'stopped';
  private error: string | null = null;
  private health: TunnelHealth = { state: 'unknown' };
  private desired = false;
  private generation = 0;
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private pending: (() => void) | null = null;
  private probing = false;
  private failures = 0;
  private port = 0;

  constructor(options: RemoteTunnelOptions = {}) {
    this.spawnFn = options.spawn ?? (nodeSpawn as unknown as SpawnFn);
    this.fetchFn = options.fetch ?? null;
    this.exists = options.exists ?? existsSync;
    this.platform = options.platform ?? process.platform;
    this.env = options.env ?? process.env;
    this.startTimeoutMs = options.startTimeoutMs ?? 90_000;
    this.healthIntervalMs = options.healthIntervalMs ?? 15_000;
    this.healthTimeoutMs = options.healthTimeoutMs ?? 7_000;
    this.retryDelays = options.retryDelays ?? [1000, 2000, 5000, 10000, 30000];
    this.log = options.log ?? (() => undefined);
  }

  snapshot(): TunnelSnapshot {
    return {
      state: this.state,
      url: this.url,
      error: this.error,
      health: { ...this.health },
      addressChanged: this.addressChanged,
      retryCount: this.retryCount,
    };
  }

  get isActive(): boolean {
    return this.desired;
  }

  get publicUrl(): string | null {
    return this.url;
  }

  executable(): string {
    const candidates =
      this.platform === 'win32'
        ? [
            join(this.env.ProgramFiles || 'C:/Program Files', 'cloudflared', 'cloudflared.exe'),
            join(this.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'cloudflared', 'cloudflared.exe'),
          ]
        : ['/usr/local/bin/cloudflared', '/usr/bin/cloudflared', '/opt/homebrew/bin/cloudflared'];
    return candidates.find((p) => this.exists(p)) ?? 'cloudflared';
  }

  start(port: number): Promise<string> {
    if (this.desired) return Promise.reject(new Error('公网通道正在运行或自动重连，请勿重复启动'));
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      return Promise.reject(new Error('invalid listener port'));
    }
    this.desired = true;
    this.port = port;
    this.retryCount = 0;
    this.error = null;
    this.generation += 1;
    return this.attempt(this.generation);
  }

  acknowledgeAddress(): void {
    this.addressChanged = false;
  }

  stop(): void {
    this.desired = false;
    this.generation += 1;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.healthTimer) clearInterval(this.healthTimer);
    this.retryTimer = null;
    this.healthTimer = null;
    const child = this.child;
    this.child = null;
    const pending = this.pending;
    this.pending = null;
    pending?.();
    this.url = null;
    this.state = 'stopped';
    this.error = null;
    this.health = { state: 'stopped' };
    if (child) {
      try {
        child.kill();
      } catch {
        /* already gone */
      }
    }
  }

  private attempt(generation: number): Promise<string> {
    this.state = this.retryCount ? 'reconnecting' : 'starting';
    this.url = null;
    this.health = { state: 'checking' };
    this.failures = 0;

    return new Promise<string>((resolve, reject) => {
      let tail = '';
      let host: string | null = null;
      let registered = false;
      let settled = false;
      let closed = false;

      let child: TunnelChild;
      try {
        child = this.spawnFn(
          this.executable(),
          ['tunnel', '--no-autoupdate', '--url', `http://127.0.0.1:${this.port}`],
          { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] },
        );
      } catch (err) {
        this.desired = false;
        this.state = 'error';
        this.error = `cloudflared: ${(err as Error).message}`;
        reject(new Error(this.error));
        return;
      }
      this.child = child;

      const current = (): boolean => this.desired && this.generation === generation && this.child === child;

      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (this.pending === cancel) this.pending = null;
        if (error) reject(error);
        else resolve(host as string);
      };
      const cancel = (): void => finish(new Error('Tunnel stopped'));
      this.pending = cancel;

      const disconnected = (error: Error, fatal = false): void => {
        if (closed) return;
        closed = true;
        finish(error);
        if (this.child !== child) return;
        this.child = null;
        this.url = null;
        if (this.healthTimer) clearInterval(this.healthTimer);
        this.healthTimer = null;
        this.health = { state: 'unreachable' };
        this.error = error.message;
        this.log('tunnel.disconnected', { reason: error.message, retry: !fatal && this.desired });
        if (fatal) this.desired = false;
        if (this.desired && this.generation === generation) this.schedule(generation);
        else if (this.state !== 'stopped') this.state = 'error';
      };

      const timer = setTimeout(() => {
        disconnected(new Error('Cloudflare startup timed out'));
        try {
          child.kill();
        } catch {
          /* ignore */
        }
      }, this.startTimeoutMs);

      const onOutput = (chunk: Buffer | string): void => {
        if (!current()) return;
        tail = (tail + chunk.toString()).slice(-OUTPUT_TAIL_CHARS);
        const hosts = tail.match(HOST_RE) ?? [];
        host = hosts.find((h) => !h.toLowerCase().includes('api.trycloudflare.com'))?.toLowerCase() ?? host;
        if (REGISTERED_RE.test(tail)) registered = true;
        if (host && registered && !settled) {
          this.addressChanged = Boolean(this.lastUrl && this.lastUrl !== host);
          if (this.addressChanged) this.log('tunnel.address_changed');
          this.url = host;
          this.lastUrl = host;
          this.state = 'running';
          this.error = null;
          this.log('tunnel.connected', { recovered: this.retryCount > 0 });
          finish();
          if (this.healthIntervalMs > 0 && this.fetchFn) {
            void this.probe();
            this.healthTimer = setInterval(() => void this.probe(), this.healthIntervalMs);
            (this.healthTimer as { unref?: () => void }).unref?.();
          }
        }
      };

      child.stdout?.on('data', onOutput);
      child.stderr?.on('data', onOutput);
      child.on('error', (e) =>
        disconnected(new Error(`cloudflared: ${e.code ?? e.message}`), e.code === 'ENOENT'),
      );
      child.on('close', (code) => disconnected(new Error(`Cloudflare exited: ${code}`)));
    });
  }

  private schedule(generation: number): void {
    this.retryCount += 1;
    const delay = this.retryDelays[Math.min(this.retryCount - 1, this.retryDelays.length - 1)];
    this.state = 'reconnecting';
    this.log('tunnel.retry_scheduled', { attempt: this.retryCount, delayMs: delay });
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.desired && this.generation === generation) {
        this.attempt(generation).catch(() => undefined);
      }
    }, delay);
    (this.retryTimer as { unref?: () => void }).unref?.();
  }

  /** Exposed for tests; normally driven by the interval timer. */
  async probe(): Promise<void> {
    if (!this.desired || !this.url || this.probing || !this.fetchFn) return;
    this.probing = true;
    const url = this.url;
    const child = this.child;
    const generation = this.generation;
    const started = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.healthTimeoutMs);
    try {
      const response = await this.fetchFn(`${url}/healthz`, { signal: controller.signal, redirect: 'error' });
      let data: unknown = null;
      try {
        data = await response.json();
      } catch {
        /* non-JSON */
      }
      if (this.child !== child || this.generation !== generation) return;
      const service = (data as { service?: unknown } | null)?.service;
      if (!response.ok || service !== HEALTH_SERVICE_NAME) {
        throw new Error(`PUBLIC_HEALTH_HTTP_${response.status}`);
      }
      this.health = { state: 'healthy', latencyMs: Date.now() - started, checkedAt: new Date().toISOString() };
      this.state = 'running';
      this.error = null;
      this.failures = 0;
      this.retryCount = 0;
    } catch (e) {
      if (this.child !== child || this.generation !== generation) return;
      this.failures += 1;
      const err = e as { message?: string; cause?: { code?: string } };
      this.health = {
        state: 'unreachable',
        checkedAt: new Date().toISOString(),
        failures: this.failures,
        reason: String(err.cause?.code ?? err.message ?? e).slice(0, 120),
      };
      this.state = 'degraded';
      // Keep the current address: a failed self-probe does not mean the
      // remote client cannot reach us.
      this.error = '本机公网自检失败；保留当前地址，不代表远端一定不可达';
      this.log('tunnel.health_failed', { failures: this.failures, reason: this.health.reason });
    } finally {
      clearTimeout(timeout);
      this.probing = false;
    }
  }
}
