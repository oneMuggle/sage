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

export interface BridgeDebugger {
  attach(protocolVersion: string): void;
  detach?(): void;
  sendCommand(method: string, params?: Record<string, unknown>): Promise<unknown>;
}

export interface BridgeWebContents {
  debugger: BridgeDebugger;
  getURL(): string;
  getTitle(): string;
  getUserAgent(): string;
  loadURL(url: string): Promise<void>;
  capturePage(): Promise<{ toPNG(): Uint8Array }>;
  isDestroyed(): boolean;
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
}

export interface BridgeRequest {
  method: string;
  params?: Record<string, unknown>;
  targetId?: string;
  headless?: boolean;
}

interface TargetEntry {
  id: string;
  win: BridgeWindow;
  attached: boolean;
}

type Mode = 'headless' | 'visible';

const PROTOCOL_VERSION = '1.3';

/** 允许透传到 webContents.debugger 的域；写入类 Storage 命令被单独拦截。 */
const DEBUGGER_PREFIXES = ['Page.', 'Runtime.', 'Network.'];

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
  private readonly targets = new Map<Mode, Map<string, TargetEntry>>();

  constructor(private readonly deps: BridgeDeps) {
    this.targets.set('headless', new Map());
    this.targets.set('visible', new Map());
  }

  async dispatch(request: BridgeRequest): Promise<unknown> {
    const method = String(request.method || '');
    if (!method) throw new Error('missing method');
    const mode = modeOf(request);
    const params = request.params ?? {};

    switch (method) {
      case 'Target.getTargets':
        return this.getTargets(mode);
      case 'Target.createTarget':
        return this.createTarget(mode, String(params.url || 'about:blank'));
      case 'Target.closeTarget':
        return this.closeTarget(mode, String(params.targetId || ''));
      case 'Target.attachToTarget': {
        const entry = await this.resolveTarget(mode, request.targetId, false);
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
            await this.deps.getSession().cookies.set(
              toElectronCookie(cookie as Record<string, unknown>),
            );
          }
        }
        return {};
      }
      case 'Page.captureScreenshot': {
        const entry = await this.resolveTarget(mode, request.targetId, false);
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
        const entry = await this.resolveTarget(mode, request.targetId, true);
        return this.sendToDebugger(entry, method, params);
      }
      default:
        if (DEBUGGER_PREFIXES.some((prefix) => method.startsWith(prefix))) {
          const entry = await this.resolveTarget(mode, request.targetId, true);
          return this.sendToDebugger(entry, method, params);
        }
        throw new Error(`unsupported method: ${method}`);
    }
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

  private getTargets(mode: Mode): { targetInfos: Array<Record<string, unknown>> } {
    const infos: Array<Record<string, unknown>> = [];
    for (const entry of this.targets.get(mode)?.values() ?? []) {
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

  private async createTarget(mode: Mode, url: string): Promise<{ targetId: string }> {
    const id = this.deps.randomId();
    const win = await this.deps.createWindow(mode === 'visible');
    await win.webContents.loadURL(url || 'about:blank');
    this.targets.get(mode)?.set(id, { id, win, attached: false });
    this.deps.log?.(`agent-browser: created ${mode} target ${id}`);
    return { targetId: id };
  }

  private closeTarget(mode: Mode, targetId: string): Record<string, unknown> {
    const map = this.targets.get(mode);
    const entry = map?.get(targetId);
    if (!entry) throw new Error(`unknown targetId: ${targetId}`);
    map?.delete(targetId);
    try {
      if (!entry.win.isDestroyed()) entry.win.close();
    } catch {
      /* best effort */
    }
    return { success: true };
  }

  private async resolveTarget(
    mode: Mode,
    targetId: string | undefined,
    createIfMissing: boolean,
  ): Promise<TargetEntry> {
    const map = this.targets.get(mode);
    if (!map) throw new Error(`unknown mode: ${mode}`);
    if (targetId) {
      const entry = map.get(targetId);
      if (!entry) throw new Error(`unknown targetId: ${targetId}`);
      return entry;
    }
    for (const entry of map.values()) {
      if (!entry.win.isDestroyed()) return entry;
    }
    if (!createIfMissing) throw new Error('no page target');
    const created = await this.createTarget(mode, 'about:blank');
    const entry = map.get(created.targetId);
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
    return entry.win.webContents.debugger.sendCommand(method, params);
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
        sendJson(res, 400, {
          error: { message: error instanceof Error ? error.message : String(error) },
        });
      }
    })();
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
            server.close(() => done());
          }),
      });
    });
  });
}
