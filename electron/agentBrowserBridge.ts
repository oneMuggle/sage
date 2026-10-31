/**
 * 内置 Agent 浏览器桥（P1）。
 *
 * Electron 21 的 `--remote-debugging-port` 浏览器端点不支持 Target.createTarget，
 * 因此这里由主进程提供一个小型 HTTP 桥：后端的 CDP 客户端在 embedded 模式下
 * 把每条命令 POST 到本桥，桥按命令白名单操作 Sage 自己的 BrowserWindow：
 *
 * - Target.*：目标注册表（headless / visible 两套，互不可见）
 * - Page/Runtime/Network.*：转发到 webContents.debugger（Chromium 106 支持）
 * - Storage/Network cookie：走 Electron session.cookies（Storage 域不被支持）
 * - Page.captureScreenshot：webContents.capturePage()
 *
 * 安全：仅监听 127.0.0.1，随机 token 头校验，body 上限 8 MiB，未知命令拒绝。
 * 本文件不 import electron —— BrowserWindow/session 由调用方注入，便于单测。
 */

import { randomBytes } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { Duplex } from 'node:stream';
import { WebSocketServer } from 'ws';

export interface BridgeDebugger {
  attach(protocolVersion: string): void;
  detach?(): void;
  sendCommand(method: string, params?: Record<string, unknown>): Promise<unknown>;
  on?(
    event: 'message',
    listener: (
      event: unknown,
      method: string,
      params: Record<string, unknown>,
      sessionId?: string,
    ) => void,
  ): void;
}

export interface BridgeWebContents {
  debugger: BridgeDebugger;
  getURL(): string;
  getTitle(): string;
  getUserAgent(): string;
  loadURL(url: string): Promise<void>;
  capturePage(): Promise<{ toPNG(): Uint8Array }>;
  isDestroyed(): boolean;
  on?(event: 'did-finish-load', listener: () => void): void;
}

export interface BridgeWindow {
  webContents: BridgeWebContents;
  show(): void;
  focus?(): void;
  close(): void;
  isDestroyed(): boolean;
}

export interface BridgeCookie {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  secure?: boolean;
  httpOnly?: boolean;
  expirationDate?: number;
  sameSite?: string;
}

export interface BridgeSession {
  cookies: {
    get(filter: Record<string, unknown>): Promise<BridgeCookie[]>;
    set(details: Record<string, unknown>): Promise<void>;
  };
  setDownloadPath?(path: string): void;
}

export interface BridgeDeps {
  createWindow(visible: boolean): Promise<BridgeWindow> | BridgeWindow;
  getSession(): BridgeSession;
  randomId(): string;
  log?(message: string): void;
  /** 订阅 Electron will-download，把下载事件转成 CDP Browser.download* 帧。 */
  onDownload?(handler: (method: string, params: Record<string, unknown>) => void): void;
}

export interface BridgeRequest {
  method: string;
  params?: Record<string, unknown>;
  targetId?: string;
  headless?: boolean;
  /** 后端 BrowserSession.browser_id；目标表按它隔离（渲染池/登录/交互互不串页）。 */
  session?: string;
}

interface TargetEntry {
  id: string;
  win: BridgeWindow;
  attached: boolean;
  /** 已为哪些 WS sessionId 订阅了 Page/Network 事件（避免重复挂监听）。 */
  pageSubscriptions?: Set<string>;
  networkSubscriptions?: Set<string>;
}

type Mode = 'headless' | 'visible';

const PROTOCOL_VERSION = '1.3';

/** 允许透传到 webContents.debugger 的域；写入类 Storage 命令被单独拦截。 */
const DEBUGGER_PREFIXES = ['Page.', 'Runtime.', 'Network.', 'Input.'];

function modeOf(request: BridgeRequest): Mode {
  return request.headless ? 'headless' : 'visible';
}

function capitalizeSameSite(value: string): string {
  const lower = value.toLowerCase();
  if (lower === 'strict') return 'Strict';
  if (lower === 'none' || lower === 'no_restriction') return 'None';
  return 'Lax';
}

function electronSameSite(value: string): string {
  const lower = value.toLowerCase();
  if (lower === 'strict') return 'strict';
  if (lower === 'none') return 'no_restriction';
  return 'lax';
}

function cookieUrl(cookie: BridgeCookie): string {
  const scheme = cookie.secure ? 'https' : 'http';
  const host = (cookie.domain || '').replace(/^\./, '') || 'localhost';
  const path = cookie.path || '/';
  return `${scheme}://${host}${path}`;
}

function toCdpCookie(cookie: BridgeCookie): Record<string, unknown> {
  return {
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain || '',
    path: cookie.path || '/',
    expires:
      typeof cookie.expirationDate === 'number' && cookie.expirationDate > 0
        ? cookie.expirationDate
        : -1,
    httpOnly: Boolean(cookie.httpOnly),
    secure: Boolean(cookie.secure),
    sameSite: capitalizeSameSite(cookie.sameSite || 'lax'),
  };
}

function toElectronCookie(cookie: Record<string, unknown>): Record<string, unknown> {
  const source = cookie as unknown as BridgeCookie;
  const details: Record<string, unknown> = {
    url: cookieUrl(source),
    name: String(cookie.name ?? ''),
    value: String(cookie.value ?? ''),
    path: String(cookie.path ?? '/'),
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly),
    sameSite: electronSameSite(String(cookie.sameSite ?? 'lax')),
  };
  const domain = String(cookie.domain ?? '');
  if (domain) details.domain = domain;
  const expires = cookie.expires;
  if (typeof expires === 'number' && expires > 0) {
    details.expirationDate = expires;
  }
  return details;
}

export class AgentBrowserBridge {
  /** key = `${mode}|${session}`；session 由后端 browser_id 提供。 */
  private readonly targets = new Map<string, Map<string, TargetEntry>>();
  private readonly eventClients = new Set<(message: Record<string, unknown>) => void>();

  constructor(private readonly deps: BridgeDeps) {
    deps.onDownload?.((method, params) => this.emitEvent({ method, params }));
  }

  /** 注册 WS 事件客户端；返回注销函数。 */
  attachEventClient(send: (message: Record<string, unknown>) => void): () => void {
    this.eventClients.add(send);
    return () => {
      this.eventClients.delete(send);
    };
  }

  private emitEvent(message: Record<string, unknown>): void {
    for (const client of this.eventClients) {
      try {
        client(message);
      } catch {
        /* 单个客户端异常不影响其他订阅者 */
      }
    }
  }

  private scope(mode: Mode, session: string): Map<string, TargetEntry> {
    const key = `${mode}|${session || 'default'}`;
    let map = this.targets.get(key);
    if (!map) {
      map = new Map();
      this.targets.set(key, map);
    }
    return map;
  }

  async dispatch(request: BridgeRequest): Promise<unknown> {
    const method = String(request.method || '');
    if (!method) throw new Error('missing method');
    const mode = modeOf(request);
    const params = request.params ?? {};
    const scope = this.scope(mode, String(request.session || 'default'));

    switch (method) {
      case 'Target.getTargets':
        return this.getTargets(scope);
      case 'Target.createTarget':
        return this.createTarget(scope, mode, String(params.url || 'about:blank'));
      case 'Target.closeTarget':
        return this.closeTarget(scope, String(params.targetId || ''));
      case 'Target.attachToTarget': {
        const targetId = String(params.targetId ?? request.targetId ?? '');
        const entry = await this.resolveTarget(scope, mode, targetId, false);
        return { sessionId: `sage-${entry.id}` };
      }
      case 'Browser.getVersion':
        return {
          protocolVersion: PROTOCOL_VERSION,
          product: `Chrome/${process.versions.chrome ?? '106'}`,
          jsVersion: process.versions.v8 ?? '',
        };
      case 'Browser.setDownloadBehavior': {
        const downloadPath = typeof params.downloadPath === 'string' ? params.downloadPath : '';
        if (downloadPath) this.deps.getSession().setDownloadPath?.(downloadPath);
        return {};
      }
      case 'Storage.getCookies':
      case 'Network.getCookies': {
        const cookies = await this.deps.getSession().cookies.get({});
        return { cookies: cookies.map(toCdpCookie) };
      }
      case 'Storage.setCookies': {
        const cookies = Array.isArray(params.cookies) ? params.cookies : [];
        for (const cookie of cookies) {
          if (cookie && typeof cookie === 'object') {
            await this.deps
              .getSession()
              .cookies.set(toElectronCookie(cookie as Record<string, unknown>));
          }
        }
        return {};
      }
      case 'Page.captureScreenshot': {
        const entry = await this.resolveTarget(scope, mode, request.targetId, false);
        const image = await entry.win.webContents.capturePage();
        return { data: Buffer.from(image.toPNG()).toString('base64') };
      }
      case 'Page.enable':
      case 'Network.enable':
      case 'Page.navigate':
      case 'Page.addScriptToEvaluateOnNewDocument':
      case 'Page.getNavigationHistory':
      case 'Runtime.evaluate':
      case 'Runtime.enable': {
        const entry = await this.resolveTarget(scope, mode, request.targetId, true);
        return this.sendToDebugger(entry, method, params);
      }
      default:
        if (DEBUGGER_PREFIXES.some((prefix) => method.startsWith(prefix))) {
          const entry = await this.resolveTarget(scope, mode, request.targetId, true);
          return this.sendToDebugger(entry, method, params);
        }
        throw new Error(`unsupported method: ${method}`);
    }
  }

  /** 处理一条 WS CDP 消息（id/method/params[/sessionId]）。 */
  async handleSocketMessage(
    raw: string,
    session: string,
    headless: boolean,
    send: (message: Record<string, unknown>) => void,
  ): Promise<void> {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    const id = message.id;
    const method = typeof message.method === 'string' ? message.method : '';
    if (id === undefined || id === null || !method) return;
    const mode: Mode = headless ? 'headless' : 'visible';
    try {
      let result: unknown;
      const sessionId = typeof message.sessionId === 'string' ? message.sessionId : '';
      if (sessionId) {
        const entry = this.entryForSessionId(mode, session, sessionId);
        result = await this.sendToDebugger(
          entry,
          method,
          (message.params as Record<string, unknown>) || {},
        );
        if (method === 'Page.enable') this.subscribePageEvents(entry, sessionId);
        if (method === 'Network.enable') this.subscribeNetworkEvents(entry, sessionId);
      } else {
        result = await this.dispatch({
          method,
          params: (message.params as Record<string, unknown>) || {},
          session,
          headless,
        });
      }
      send({ id, result });
    } catch (error) {
      send({
        id,
        error: { message: error instanceof Error ? error.message : String(error) },
      });
    }
  }

  private entryForSessionId(mode: Mode, session: string, sessionId: string): TargetEntry {
    const targetId = sessionId.startsWith('sage-') ? sessionId.slice(5) : sessionId;
    const entry = this.scope(mode, session).get(targetId);
    if (!entry) throw new Error(`unknown sessionId: ${sessionId}`);
    return entry;
  }

  private subscribePageEvents(entry: TargetEntry, sessionId: string): void {
    if (!entry.pageSubscriptions) entry.pageSubscriptions = new Set();
    if (entry.pageSubscriptions.has(sessionId)) return;
    entry.pageSubscriptions.add(sessionId);
    entry.win.webContents.on?.('did-finish-load', () => {
      this.emitEvent({
        method: 'Page.loadEventFired',
        params: { timestamp: Date.now() / 1000 },
        sessionId,
      });
    });
  }

  private subscribeNetworkEvents(entry: TargetEntry, sessionId: string): void {
    if (!entry.networkSubscriptions) entry.networkSubscriptions = new Set();
    if (entry.networkSubscriptions.has(sessionId)) return;
    entry.networkSubscriptions.add(sessionId);
    entry.win.webContents.debugger.on?.('message', (_event, method, params) => {
      if (method === 'Network.responseReceived') {
        this.emitEvent({ method, params, sessionId });
      }
    });
  }

  /** 关闭全部窗口（应用退出时调用）。 */
  closeAll(): void {
    for (const map of this.targets.values()) {
      for (const entry of map.values()) {
        try {
          if (!entry.win.isDestroyed()) entry.win.close();
        } catch {
          /* best effort */
        }
      }
      map.clear();
    }
  }

  private getTargets(scope: Map<string, TargetEntry>): {
    targetInfos: Array<Record<string, unknown>>;
  } {
    const infos: Array<Record<string, unknown>> = [];
    for (const entry of scope.values()) {
      if (entry.win.isDestroyed()) continue;
      infos.push({
        targetId: entry.id,
        type: 'page',
        url: entry.win.webContents.getURL(),
        title: entry.win.webContents.getTitle(),
      });
    }
    return { targetInfos: infos };
  }

  private async createTarget(
    scope: Map<string, TargetEntry>,
    mode: Mode,
    url: string,
  ): Promise<{ targetId: string }> {
    const targetUrl = url || 'about:blank';
    if (!/^(https?:\/\/|about:blank)/i.test(targetUrl)) {
      throw new Error(`unsupported url scheme: ${targetUrl.slice(0, 32)}`);
    }
    const id = this.deps.randomId();
    const win = await this.deps.createWindow(mode === 'visible');
    const entry: TargetEntry = { id, win, attached: false };
    // 先登记再加载：加载失败/超时也必须能按 targetId 回收窗口
    scope.set(id, entry);
    try {
      await win.webContents.loadURL(targetUrl);
    } catch (error) {
      scope.delete(id);
      try {
        if (!win.isDestroyed()) win.close();
      } catch {
        /* best effort */
      }
      throw error;
    }
    this.deps.log?.(`agent-browser: created ${mode} target ${id}`);
    return { targetId: id };
  }

  private closeTarget(scope: Map<string, TargetEntry>, targetId: string): Record<string, unknown> {
    const entry = scope.get(targetId);
    if (!entry) throw new Error(`unknown targetId: ${targetId}`);
    scope.delete(targetId);
    try {
      if (!entry.win.isDestroyed()) entry.win.close();
    } catch {
      /* best effort */
    }
    return { success: true };
  }

  private async resolveTarget(
    scope: Map<string, TargetEntry>,
    mode: Mode,
    targetId: string | undefined,
    createIfMissing: boolean,
  ): Promise<TargetEntry> {
    if (targetId) {
      const entry = scope.get(targetId);
      if (!entry) throw new Error(`unknown targetId: ${targetId}`);
      return entry;
    }
    for (const entry of scope.values()) {
      if (!entry.win.isDestroyed()) return entry;
    }
    if (!createIfMissing) throw new Error('no page target');
    const created = await this.createTarget(scope, mode, 'about:blank');
    const entry = scope.get(created.targetId);
    if (!entry) throw new Error('failed to create target');
    return entry;
  }

  private async sendToDebugger(
    entry: TargetEntry,
    method: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    if (entry.win.isDestroyed()) throw new Error('target closed');
    if (!entry.attached) {
      try {
        entry.win.webContents.debugger.attach(PROTOCOL_VERSION);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (!message.toLowerCase().includes('already attached')) throw error;
      }
      entry.attached = true;
    }
    try {
      return await entry.win.webContents.debugger.sendCommand(method, params);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!/not attached|not connected/i.test(message)) throw error;
      // renderer 重启 / DevTools 抢占后 debugger 被 detach：重连一次
      entry.attached = false;
      entry.win.webContents.debugger.attach(PROTOCOL_VERSION);
      entry.attached = true;
      return entry.win.webContents.debugger.sendCommand(method, params);
    }
  }
}

const MAX_BODY_BYTES = 8 * 1024 * 1024;

async function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error('body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function sendJson(res: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

export interface AgentBrowserBridgeHandle {
  port: number;
  token: string;
  close(): Promise<void>;
}

export interface StartBridgeOptions {
  token?: string;
  host?: string;
}

/**
 * 启动本地 HTTP 桥。返回端口与 token（调用方通过 env 传给后端）。
 */
export function startAgentBrowserBridge(
  deps: BridgeDeps,
  options: StartBridgeOptions = {},
): Promise<AgentBrowserBridgeHandle> {
  const bridge = new AgentBrowserBridge(deps);
  const token = options.token ?? randomBytes(24).toString('base64url');
  const wss = new WebSocketServer({ noServer: true });
  const server = createServer((req, res) => {
    void (async () => {
      try {
        if (req.method !== 'POST' || req.url !== '/command') {
          sendJson(res, 404, { error: { message: 'not found' } });
          return;
        }
        if (req.headers['x-sage-bridge-token'] !== token) {
          sendJson(res, 401, { error: { message: 'unauthorized' } });
          return;
        }
        const body = await readBody(req);
        const request = JSON.parse(body) as BridgeRequest;
        try {
          const result = await bridge.dispatch(request);
          sendJson(res, 200, { result });
        } catch (error) {
          sendJson(res, 200, {
            error: { message: error instanceof Error ? error.message : String(error) },
          });
        }
      } catch (error) {
        if (!res.writableEnded && !res.destroyed) {
          sendJson(res, 400, {
            error: { message: error instanceof Error ? error.message : String(error) },
          });
        }
      }
    })();
  });

  server.on('upgrade', (req, socket, head) => {
    let url: URL;
    try {
      url = new URL(req.url ?? '', 'http://127.0.0.1');
    } catch {
      socket.destroy();
      return;
    }
    if (url.pathname !== '/devtools/browser/embedded') {
      socket.destroy();
      return;
    }
    if (url.searchParams.get('token') !== token) {
      socket.destroy();
      return;
    }
    const session = url.searchParams.get('session') || 'default';
    const headless = url.searchParams.get('headless') === '1';
    wss.handleUpgrade(req, socket as Duplex, head, (ws) => {
      const send = (message: Record<string, unknown>): void => {
        if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(message));
      };
      const unsubscribe = bridge.attachEventClient(send);
      ws.on('message', (data) => {
        void bridge.handleSocketMessage(String(data), session, headless, send);
      });
      ws.on('close', unsubscribe);
      ws.on('error', unsubscribe);
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, options.host ?? '127.0.0.1', () => {
      const address = server.address() as AddressInfo;
      resolve({
        port: address.port,
        token,
        close: () =>
          new Promise<void>((done) => {
            bridge.closeAll();
            for (const client of wss.clients) client.terminate();
            wss.close();
            server.close(() => done());
          }),
      });
    });
  });
}
