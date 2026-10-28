/**
 * Arena token window (plan §5.9, P3) — hidden Electron window that mints
 * reCAPTCHA V3 tokens for arena.ai and pushes them to the backend cache
 * (`backend/services/arena_token_cache.py`).
 *
 * Chain (plan §5.9):
 *   hidden BrowserWindow(partition 'persist:arena-token')
 *     → https://arena.ai/agent/  → grecaptcha.enterprise.execute
 *     → POST {backend}/api/v1/arena/token-window/push (Bearer local auth)
 *
 * The window is *backend-driven*: it polls GET /token-window/state every
 * poll_interval_sec (from the state payload) and reacts to
 *   needed      → mint immediately (acceptance: < 3 s end-to-end)
 *   want_proxy  → session.setProxy({proxyRules: state.proxy_url}) + reload
 *                 (the backend already mapped the upstream proxy onto the
 *                 local CONNECT relay — Chromium ignores proxy credentials)
 *   enabled=false → destroy the window and stop
 *
 * Reference semantics preserved from reference/ArenCard/token_server.py:
 *   - "ready is only a hint": mint even when the ready flag is stale, and
 *     retry once after a reload (`mint_token` / `ensure_alive`).
 *   - readiness needs BOTH document.readyState === 'complete' AND
 *     window.grecaptcha?.enterprise (the earlier readyState-only check made
 *     the first mint after startup always fail).
 *   - warmup mint right after ready, so health.ready flips true immediately.
 *   - anti-throttle switches live in electron/main.ts (app-level); this
 *     window only adds backgroundThrottling: false as the second line of
 *     defense.
 *
 * Backend unreachable (restart window): pushes and state polls back off
 * exponentially (1 s → 30 s cap) and never crash the main process.
 *
 * Pure module on purpose: no top-level side effects, every effect
 * (BrowserWindow, fetch, sleep, clock) is an injectable seam so
 * electron/__tests__/arenaTokenWindow.test.ts can stub them.
 */
import { app, BrowserWindow, session } from 'electron';
import { fetchCompat } from './fetchCompat';

const ARENA_TOKEN_PARTITION = 'persist:arena-token';

// Measured constants (S0 spike + reference token_server.py).
const V3_KEY = '6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0';
const ACTION = 'agentic_chat_submit';
const START_URL = 'https://arena.ai/agent/';
const IP_ECHO_URL = 'https://api.ipify.org?format=json';

const READY_TIMEOUT_MS = 90_000;
const RELOAD_READY_TIMEOUT_MS = 60_000;
const MINT_TIMEOUT_MS = 30_000;
const PUSH_BACKOFF_MAX_MS = 30_000;
const POLL_MIN_MS = 500;
const POLL_MAX_MS = 60_000;

const JS_MINT =
  `window.__tok=null;window.__err=null;` +
  `grecaptcha.enterprise.ready(function(){` +
  `grecaptcha.enterprise.execute('${V3_KEY}',{action:'${ACTION}'})` +
  `.then(function(t){window.__tok=t;})` +
  `.catch(function(e){window.__err=String(e);});});`;

const JS_READY = `document.readyState === 'complete' && !!(window.grecaptcha && window.grecaptcha.enterprise)`;
const JS_GRECAPTCHA_ALIVE = `!!(window.grecaptcha && window.grecaptcha.enterprise)`;
const JS_PROBE_IP =
  `window.__ip=null;` +
  `fetch('${IP_ECHO_URL}')` +
  `.then(function(r){return r.json();})` +
  `.then(function(d){window.__ip=d.ip;})` +
  `.catch(function(e){window.__ip='ERR '+e;});`;

export interface ArenaTokenStatus {
  running: boolean;
  ready: boolean;
  count: number;
  error: string;
  exitIp: string;
  ua: string;
  uptimeMs: number;
  proxyUrl: string;
  lastPushAgeMs: number | null;
}

interface TokenWindowStateResp {
  enabled: boolean;
  needed: boolean;
  reject_count: number;
  want_proxy: boolean;
  proxy_url: string;
  poll_interval_sec: number;
}

interface WindowLike {
  loadURL(url: string): Promise<void>;
  reload(): void;
  destroy(): void;
  isDestroyed(): boolean;
  webContents: {
    executeJavaScript(code: string, userGesture?: boolean): Promise<unknown>;
  };
}

interface SessionLike {
  setProxy(config: { proxyRules?: string; mode?: string }): Promise<void>;
}

export interface ArenaTokenControllerOptions {
  backendUrl: string;
  authToken: () => string | undefined;
  log?: (msg: string) => void;
  /** test seams (defaults wire the real Electron/fetch/timers) */
  createWindow?: () => WindowLike;
  sessionFromPartition?: () => SessionLike;
  fetchJson?: (
    url: string,
    init: Record<string, unknown>,
  ) => Promise<{ ok: boolean; status: number; json?: unknown }>;
  delay?: (ms: number) => Promise<void>;
  now?: () => number;
}

/**
 * Electron 把宿主 app 的 package.json name/version 拼进每个窗口的 UA
 * （… <appName>/<appVersion> Chrome/<v> Electron/<v> …）——常驻自动化特征，
 * 会压低 reCAPTCHA Enterprise 评分（P4 冒烟实测链路的环境因子之一：
 * arena.ai create-chat 403 "recaptcha validation failed"）。归一为等价
 * 纯 Chrome UA；已在 P4 真实冒烟中验证有效（同 IP + 干净 UA 呈现）。
 */
export function plainChromeUa(ua: string): string {
  return ua
    .replace(/\s+\S+\/\S+(?=\s+Chrome\/)/, '') // 宿主 app name/version token
    .replace(/\s+Electron\/\S+/, ''); // Electron token
}

export function defaultCreateWindow(): WindowLike {
  const win = new BrowserWindow({
    show: false,
    width: 1100,
    height: 800,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
      partition: ARENA_TOKEN_PARTITION,
    },
  }) as unknown as WindowLike;
  // 首次 load 之前归一化分区会话 UA（自定义 createWindow 的调用方自管）。
  try {
    const rawUa = (win as unknown as {
      webContents: { getUserAgent: () => string };
    }).webContents.getUserAgent();
    session
      .fromPartition(ARENA_TOKEN_PARTITION)
      .setUserAgent(plainChromeUa(rawUa));
  } catch {
    // 归一化失败不阻断窗口创建（降级为默认 UA）
  }
  return win;
}

async function defaultFetchJson(
  url: string,
  init: Record<string, unknown>,
): Promise<{ ok: boolean; status: number; json?: unknown }> {
  // Electron 21 bundles Node 16 (no global fetch) — fetchCompat falls back
  // to node-fetch; tests can vi.stubGlobal('fetch') instead.
  const res = await fetchCompat(url as never, init as never);
  let json: unknown;
  try {
    json = await res.json();
  } catch {
    json = undefined;
  }
  return { ok: res.ok, status: res.status, json };
}

export class ArenaTokenWindowController {
  private readonly backendUrl: string;
  private readonly authToken: () => string | undefined;
  private readonly log: (msg: string) => void;
  private readonly createWindowFn: () => WindowLike;
  private readonly sessionFn: () => SessionLike;
  private readonly fetchJson: (
    url: string,
    init: Record<string, unknown>,
  ) => Promise<{ ok: boolean; status: number; json?: unknown }>;
  private readonly delay: (ms: number) => Promise<void>;
  private readonly now: () => number;

  private window: WindowLike | null = null;
  private stopped = true;
  private running = false;
  private ready = false;
  private count = 0;
  private error = '';
  private exitIp = '';
  private ua = '';
  private proxyUrl = '';
  private startedAt = 0;
  private lastPushAt = 0;
  private minting = false;
  private pollMs = 2000;

  constructor(options: ArenaTokenControllerOptions) {
    this.backendUrl = options.backendUrl.replace(/\/+$/, '');
    this.authToken = options.authToken;
    this.log = options.log ?? (() => undefined);
    this.createWindowFn = options.createWindow ?? defaultCreateWindow;
    this.sessionFn =
      options.sessionFromPartition ?? (() => session.fromPartition(ARENA_TOKEN_PARTITION));
    this.fetchJson = options.fetchJson ?? defaultFetchJson;
    this.delay = options.delay ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.now = options.now ?? (() => Date.now());
  }

  // ── lifecycle ────────────────────────────────────────────────────────

  /** Open the window, wait for readiness, warmup-mint, start the poll loop. */
  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.stopped = false;
    this.startedAt = this.now();
    this.error = '';
    try {
      this.window = this.createWindowFn();
      await this.window.loadURL(START_URL);
      this.ready = await this.waitReady(READY_TIMEOUT_MS);
      if (!this.ready) {
        this.setError('页面 90s 未就绪（grecaptcha 未出现）');
        await this.stop();
        return;
      }
      this.log('token window ready');
      const ua = await this.evalJs('navigator.userAgent');
      if (typeof ua === 'string' && ua) this.ua = ua;
      await this.probeExitIp();
      await this.mintAndPush(); // warmup: health.ready flips immediately
    } catch (e) {
      this.setError(`启动失败: ${describe(e)}`);
    }
    if (!this.stopped) void this.pollLoop();
  }

  /** Destroy the window and stop all loops (idempotent). */
  async stop(): Promise<void> {
    this.stopped = true;
    this.running = false;
    this.ready = false;
    const win = this.window;
    this.window = null;
    if (win && !win.isDestroyed()) {
      try {
        win.destroy();
      } catch {
        /* already gone */
      }
    }
    this.log('token window stopped');
  }

  /**
   * ensure_alive semantics: no-op while grecaptcha is alive; otherwise
   * reload the page and wait for readiness again.
   */
  async reload(): Promise<boolean> {
    if (!this.window) return false;
    const alive = await this.evalJs(JS_GRECAPTCHA_ALIVE);
    if (alive === true) return true;
    this.ready = false;
    await this.window.loadURL(START_URL);
    this.ready = await this.waitReady(RELOAD_READY_TIMEOUT_MS);
    return this.ready;
  }

  /**
   * Manual proxy override (renderer `pick-proxy`). Credential-less local
   * proxies only — Chromium ignores proxy credentials, so credentialed
   * upstreams must go through the backend relay (`want_proxy` flow).
   * `null` reverts to the system proxy.
   */
  async pickProxy(proxyUrl: string | null): Promise<void> {
    const url = (proxyUrl ?? '').trim();
    if (url && /@/.test(url)) {
      throw new Error('凭据代理请走后端 want_proxy 流程（本地 relay 映射）');
    }
    await this.applyProxy(url);
  }

  status(): ArenaTokenStatus {
    const nowMs = this.now();
    return {
      running: this.running,
      ready: this.ready,
      count: this.count,
      error: this.error,
      exitIp: this.exitIp,
      ua: this.ua,
      uptimeMs: this.startedAt ? nowMs - this.startedAt : 0,
      proxyUrl: this.proxyUrl,
      lastPushAgeMs: this.lastPushAt ? nowMs - this.lastPushAt : null,
    };
  }

  // ── internals ────────────────────────────────────────────────────────

  private setError(message: string): void {
    this.error = message;
    this.log(`[arena-token] ${message}`);
  }

  private async evalJs(expr: string): Promise<unknown> {
    if (!this.window || this.window.isDestroyed()) return undefined;
    try {
      return await this.window.webContents.executeJavaScript(expr, true);
    } catch (e) {
      this.setError(`evalJs 失败: ${describe(e)}`);
      return undefined;
    }
  }

  private async waitReady(timeoutMs: number): Promise<boolean> {
    const deadline = this.now() + timeoutMs;
    while (this.now() < deadline && !this.stopped) {
      const ready = await this.evalJs(JS_READY);
      if (ready === true) return true;
      await this.delay(500);
    }
    return false;
  }

  /** Window-side exit-IP probe (reference /ip): fetch ipify inside the page. */
  private async probeExitIp(): Promise<void> {
    await this.evalJs(JS_PROBE_IP);
    const deadline = this.now() + 20_000;
    while (this.now() < deadline) {
      const ip = await this.evalJs('window.__ip');
      if (typeof ip === 'string' && ip && !ip.startsWith('ERR')) {
        this.exitIp = ip;
        this.log(`token window exit ip: ${ip}`);
        return;
      }
      if (typeof ip === 'string' && ip.startsWith('ERR')) return;
      await this.delay(300);
    }
  }

  /** One mint attempt: ensure alive → execute → poll __tok (150 ms steps). */
  private async mintOnce(timeoutMs: number): Promise<string> {
    const alive = await this.reload(); // ensure_alive (no-op when healthy)
    if (!alive) throw new Error('浏览器未就绪');
    await this.evalJs(JS_MINT);
    const deadline = this.now() + timeoutMs;
    while (this.now() < deadline && !this.stopped) {
      const tok = await this.evalJs('window.__tok');
      if (typeof tok === 'string' && tok.length > 0) return tok;
      const err = await this.evalJs('window.__err');
      if (typeof err === 'string' && err.length > 0) {
        throw new Error(`execute 失败: ${err.slice(0, 120)}`);
      }
      await this.delay(150);
    }
    throw new Error('取 token 超时');
  }

  /** Mint + push with the reference retry (reload once) and backoff. */
  private async mintAndPush(): Promise<void> {
    if (this.minting || this.stopped || !this.window) return;
    this.minting = true;
    try {
      let token: string;
      try {
        token = await this.mintOnce(MINT_TIMEOUT_MS);
      } catch (e) {
        // ready is only a hint — reload and try exactly once more
        this.setError(`首次出票失败，重载重试: ${describe(e)}`);
        this.ready = false;
        await this.window.loadURL(START_URL);
        this.ready = await this.waitReady(RELOAD_READY_TIMEOUT_MS);
        if (!this.ready) throw new Error(`重载后仍未就绪: ${describe(e)}`);
        token = await this.mintOnce(MINT_TIMEOUT_MS);
      }
      await this.pushToken(token);
      this.count += 1;
      this.lastPushAt = this.now();
      this.error = '';
    } catch (e) {
      this.setError(`出票/推送失败: ${describe(e)}`);
    } finally {
      this.minting = false;
    }
  }

  private async pushToken(token: string): Promise<void> {
    let backoffMs = 0;
    // 后端重启窗口期间指数退避重试推送，绝不向上抛（plan §5.9 生命周期）。
    for (;;) {
      if (this.stopped) return;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const tokenValue = this.authToken();
      if (tokenValue) headers.Authorization = `Bearer ${tokenValue}`;
      const result = await this.fetchJson(
        `${this.backendUrl}/api/v1/arena/token-window/push`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({ token, exit_ip: this.exitIp || undefined, ua: this.ua || undefined }),
        },
      );
      if (result.ok) return;
      if (result.status === 403 || result.status === 401) {
        // arena/token_window disabled or auth changed — stop, state poll will confirm
        this.setError(`推送被拒 (HTTP ${result.status})，停止窗口`);
        await this.stop();
        return;
      }
      backoffMs = backoffMs ? Math.min(backoffMs * 2, PUSH_BACKOFF_MAX_MS) : 1000;
      this.log(`push failed (HTTP ${result.status}), backoff ${backoffMs}ms`);
      await this.delay(backoffMs);
    }
  }

  private async pollLoop(): Promise<void> {
    let backoffMs = 0;
    while (!this.stopped) {
      await this.delay(this.pollMs);
      if (this.stopped) break;
      try {
        const headers: Record<string, string> = {};
        const tokenValue = this.authToken();
        if (tokenValue) headers.Authorization = `Bearer ${tokenValue}`;
        const result = await this.fetchJson(`${this.backendUrl}/api/v1/arena/token-window/state`, {
          method: 'GET',
          headers,
        });
        if (!result.ok) throw new Error(`HTTP ${result.status}`);
        backoffMs = 0;
        const state = (result.json ?? {}) as TokenWindowStateResp;
        this.pollMs = clamp(state.poll_interval_sec * 1000 || 2000, POLL_MIN_MS, POLL_MAX_MS);
        if (!state.enabled) {
          this.log('backend disabled the token window');
          await this.stop();
          break;
        }
        if (state.want_proxy && state.proxy_url && state.proxy_url !== this.proxyUrl) {
          await this.applyProxy(state.proxy_url);
          continue;
        }
        if (state.needed) void this.mintAndPush();
      } catch (e) {
        // backend unreachable (restart window): back off and keep polling
        backoffMs = backoffMs ? Math.min(backoffMs * 2, PUSH_BACKOFF_MAX_MS) : 1000;
        this.log(`state poll failed (${describe(e)}), backoff ${backoffMs}ms`);
        await this.delay(backoffMs);
      }
    }
  }

  /** Apply proxyRules to the isolated partition, reload, re-ready, warmup. */
  private async applyProxy(rules: string): Promise<void> {
    const ses = this.sessionFn();
    await ses.setProxy(rules ? { proxyRules: rules } : { mode: 'system' });
    this.proxyUrl = rules;
    this.exitIp = '';
    this.log(`token window proxy -> ${rules || 'system'}`);
    if (this.window && !this.stopped) {
      this.ready = false;
      await this.window.loadURL(START_URL);
      this.ready = await this.waitReady(READY_TIMEOUT_MS);
      if (this.ready) {
        await this.probeExitIp();
        await this.mintAndPush();
      }
    }
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function describe(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export interface ArenaTokenWindowDeps {
  register: RegisterIpcHandler;
  getBackendUrl: () => string;
  getAuthToken: () => string | undefined;
  log?: (msg: string) => void;
}

/**
 * Wire the renderer-controllable channels (plan §6.2):
 *   sage:arena-token:status | :start | :stop | :reload | :pick-proxy
 * The caller (electron/main.ts) wraps `register` with the isTrustedRenderer
 * guard, exactly like registerSkillsIpc/registerMediaIpc. `before-quit`
 * destroys the window. Returns the controller for direct use by smoke
 * harnesses (production callers ignore it).
 */
export function registerArenaTokenWindow(deps: ArenaTokenWindowDeps): ArenaTokenWindowController {
  const controller = new ArenaTokenWindowController({
    backendUrl: deps.getBackendUrl(),
    authToken: deps.getAuthToken,
    log: deps.log,
  });
  deps.register('sage:arena-token:status', () => controller.status());
  deps.register('sage:arena-token:start', () => controller.start());
  deps.register('sage:arena-token:stop', () => controller.stop());
  deps.register('sage:arena-token:reload', () => controller.reload());
  deps.register('sage:arena-token:pick-proxy', (...args: unknown[]) => {
    // main.ts wrapper calls handler(evt, payload); direct calls pass payload
    const raw = args.length > 1 ? args[1] : args[0];
    const payload = raw as { proxyUrl?: string | null } | undefined;
    return controller.pickProxy(payload?.proxyUrl ?? null);
  });
  app.on('before-quit', () => {
    void controller.stop();
  });
  return controller;
}
