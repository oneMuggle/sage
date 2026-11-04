/**
 * Opt-in, read-only local HTTP status API for plugins/scripts.
 *
 * Security posture:
 *   - binds 127.0.0.1 on an ephemeral port (no LAN exposure);
 *   - every request needs `Authorization: Bearer <token>`; token is 32 random
 *     bytes, rotated each app start, and discoverable via
 *     `<userData>/pet-api.json` (mode 0600 on POSIX);
 *   - only GET; Host header must match loopback, which blocks DNS rebinding;
 *   - per-IP rate limit; no CORS headers; no request bodies are read;
 *   - payload is the same sanitized view the on-screen panel shows (no raw
 *     tool errors/commands).
 */
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import {
  chmodSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import { dirname, join } from 'node:path';

import { logger } from '../logger';
import { buildStatusPayload, type PetStatusPayload } from './statusPayload';
import type { PetConfig, PetSnapshot } from './types';

export const STATUS_API_HOST = '127.0.0.1';
export const STATUS_API_MAX_URL = 2048;
export const STATUS_API_RATE_PER_MINUTE = 120;
export const STATUS_API_UNAUTH_RATE_PER_MINUTE = 10;

export interface StatusServerOptions {
  userDataDir: string;
  /** Authenticated requests per minute (default 120). */
  rateLimitPerMinute?: number;
  /** Unauthenticated requests per minute (default 10; brute-force guard). */
  unauthenticatedRatePerMinute?: number;
  now?: () => number;
}

export interface StatusServerInfo {
  enabled: boolean;
  port: number | null;
  error?: string | null;
}

export function statusTokenFile(userDataDir: string): string {
  return join(userDataDir, 'pet-api.json');
}

/** Constant-time bearer-token check; malformed headers fail closed. */
export function isAuthorizedHeader(header: string | undefined, token: string): boolean {
  if (!token || typeof header !== 'string') return false;
  const match = /^Bearer\s+([A-Za-z0-9._~-]+)$/i.exec(header.trim());
  if (!match) return false;
  const provided = createHash('sha256').update(match[1]!).digest();
  const expected = createHash('sha256').update(token).digest();
  return timingSafeEqual(provided, expected);
}

/** Fixed-window per-key rate limiter (60s windows, bounded map). */
export class RateLimiter {
  private readonly buckets = new Map<string, { count: number; resetAt: number }>();

  constructor(
    private readonly limit: number,
    private readonly now: () => number = Date.now,
  ) {}

  take(key: string): boolean {
    const at = this.now();
    // Prune expired buckets instead of clearing the whole map: a clear()
    // would reset legitimate counters (and make the limit bypassable).
    for (const [bucketKey, entry] of this.buckets) {
      if (at >= entry.resetAt) this.buckets.delete(bucketKey);
    }
    const bucket = this.buckets.get(key);
    if (!bucket) {
      this.buckets.set(key, { count: 1, resetAt: at + 60_000 });
      return true;
    }
    if (bucket.count >= this.limit) return false;
    bucket.count += 1;
    return true;
  }
}

export class PetStatusServer {
  private server: Server | null = null;
  private port: number | null = null;
  private token = '';
  private payload: PetStatusPayload | null = null;
  private startedAt = 0;
  private readonly sockets = new Set<Socket>();
  private readonly authLimiter: RateLimiter;
  private readonly unauthLimiter: RateLimiter;
  private readonly now: () => number;
  private readonly tokenFile: string;

  constructor(private readonly options: StatusServerOptions) {
    this.now = options.now ?? Date.now;
    // Separate buckets by auth state: an unauthenticated flood from a local
    // web page must not consume the authenticated consumer's quota.
    this.authLimiter = new RateLimiter(
      options.rateLimitPerMinute ?? STATUS_API_RATE_PER_MINUTE,
      this.now,
    );
    this.unauthLimiter = new RateLimiter(
      options.unauthenticatedRatePerMinute ?? STATUS_API_UNAUTH_RATE_PER_MINUTE,
      this.now,
    );
    this.tokenFile = statusTokenFile(options.userDataDir);
  }

  update(snapshot: PetSnapshot, config: PetConfig): void {
    this.payload = buildStatusPayload(snapshot, config);
  }

  getInfo(): StatusServerInfo {
    return { enabled: this.server !== null, port: this.port };
  }

  async start(): Promise<void> {
    if (this.server) return;
    const token = randomBytes(32).toString('hex');
    const server = createServer((req, res) => this.handle(req, res));
    // Bound main-process resources: this server runs in the Electron main
    // process, so a stuck client must not be able to exhaust fds/memory.
    server.maxConnections = 32;
    server.headersTimeout = 10_000;
    server.requestTimeout = 10_000;
    server.keepAliveTimeout = 5_000;
    // Track sockets so stop() revokes access immediately; `server.close()`
    // alone leaves keep-alive connections able to reach the handler.
    server.on('connection', (socket) => {
      this.sockets.add(socket);
      socket.once('close', () => this.sockets.delete(socket));
    });
    await new Promise<void>((resolve, reject) => {
      const onError = (error: Error): void => {
        server.off('listening', onListening);
        reject(error);
      };
      const onListening = (): void => {
        server.off('error', onError);
        resolve();
      };
      server.once('error', onError);
      server.once('listening', onListening);
      server.listen(0, STATUS_API_HOST);
    });

    const address = server.address();
    if (!address || typeof address === 'string') {
      server.close();
      throw new Error('status API: no bound port');
    }
    this.server = server;
    this.port = address.port;
    this.token = token;
    this.startedAt = this.now();
    try {
      this.writeTokenFile(token);
    } catch {
      // Windows AV/indexers can briefly lock the target; retry once.
      await new Promise((resolve) => setTimeout(resolve, 150));
      try {
        this.writeTokenFile(token);
      } catch (error) {
        this.stop();
        throw error;
      }
    }
    logger.info('pet: read-only status API listening', { port: this.port });
  }

  stop(): void {
    const server = this.server;
    const token = this.token;
    this.server = null;
    this.port = null;
    this.token = '';
    this.payload = null;
    if (server) {
      try {
        server.close();
      } catch {
        // Already closed / never listening.
      }
    }
    for (const socket of this.sockets) {
      try {
        socket.destroy();
      } catch {
        // Already gone.
      }
    }
    this.sockets.clear();
    // Only remove the token file if it still belongs to this instance; a
    // late stop() from a superseded start must not delete the new token.
    if (token && this.tokenFileBelongsTo(token)) {
      try {
        rmSync(this.tokenFile, { force: true });
      } catch {
        // Best-effort cleanup.
      }
    }
  }

  private tokenFileBelongsTo(token: string): boolean {
    try {
      const parsed = JSON.parse(readFileSync(this.tokenFile, 'utf8')) as { token?: unknown };
      return parsed.token === token;
    } catch {
      return false;
    }
  }

  private writeTokenFile(token: string): void {
    const body = {
      version: 1,
      pid: process.pid,
      port: this.port,
      token,
      createdAt: this.now(),
    };
    mkdirSync(dirname(this.tokenFile), { recursive: true });
    const temporary = `${this.tokenFile}.${randomBytes(6).toString('hex')}.tmp`;
    try {
      writeFileSync(temporary, `${JSON.stringify(body, null, 2)}\n`, { mode: 0o600 });
      try {
        chmodSync(temporary, 0o600);
      } catch {
        // chmod is a no-op on Windows; the file lives in the per-user dir.
      }
      renameSync(temporary, this.tokenFile);
    } finally {
      try {
        rmSync(temporary, { force: true });
      } catch {
        // Rename may already have moved it.
      }
    }
  }

  private handle(req: IncomingMessage, res: ServerResponse): void {
    const respond = (status: number, body: unknown, extra: Record<string, string> = {}): void => {
      const text = JSON.stringify(body);
      res.writeHead(status, {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
        'X-Content-Type-Options': 'nosniff',
        ...extra,
      });
      res.end(text);
    };

    try {
      if (!this.server || this.port === null) {
        respond(503, { error: 'unavailable' });
        return;
      }
      const url = req.url ?? '/';
      if (url.length > STATUS_API_MAX_URL) {
        respond(414, { error: 'uri_too_long' });
        return;
      }
      const host = (req.headers.host ?? '').toLowerCase();
      if (host !== `${STATUS_API_HOST}:${this.port}` && host !== `localhost:${this.port}`) {
        respond(403, { error: 'forbidden_host' });
        return;
      }
      if ((req.method ?? 'GET').toUpperCase() !== 'GET') {
        respond(405, { error: 'method_not_allowed' }, { Allow: 'GET' });
        return;
      }
      const hasBody =
        (req.headers['content-length'] !== undefined && req.headers['content-length'] !== '0') ||
        req.headers['transfer-encoding'] !== undefined;
      if (hasBody) {
        req.resume();
        respond(400, { error: 'body_not_allowed' }, { Connection: 'close' });
        return;
      }
      // Bucket by auth state, not by IP: every loopback client shares
      // 127.0.0.1, so an unauthenticated browser flood must not consume the
      // authenticated consumer's quota (and 127.0.0.0/8 rotation must not
      // create fresh buckets).
      const authorized = isAuthorizedHeader(req.headers.authorization, this.token);
      const limiter = authorized ? this.authLimiter : this.unauthLimiter;
      if (!limiter.take(authorized ? 'auth' : 'unauthenticated')) {
        respond(429, { error: 'rate_limited' }, { 'Retry-After': '60' });
        return;
      }
      if (!authorized) {
        respond(401, { error: 'unauthorized' }, { 'WWW-Authenticate': 'Bearer' });
        return;
      }
      const path = url.split('?', 1)[0];
      if (path === '/v1/health') {
        respond(200, { ok: true, version: 1, uptimeMs: this.now() - this.startedAt });
        return;
      }
      if (path === '/v1/status') {
        if (!this.payload) {
          respond(503, { error: 'not_ready' });
          return;
        }
        respond(200, this.payload);
        return;
      }
      respond(404, { error: 'not_found' });
    } catch (error) {
      logger.warn('pet: status API handler failed', {
        err: error instanceof Error ? error.message : String(error),
      });
      try {
        respond(500, { error: 'internal' });
      } catch {
        // Response may already be partially written.
      }
    }
  }
}
