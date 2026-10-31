import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { request as httpRequest } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { DEFAULT_PET_CONFIG } from '../pet/config';
import {
  isAuthorizedHeader,
  PetStatusServer,
  RateLimiter,
  statusTokenFile,
} from '../pet/statusServer';
import type { PetSnapshot } from '../pet/types';

const NOW = 1_700_000_000_000;

function snapshot(): PetSnapshot {
  return {
    action: 'thinking',
    detail: null,
    sessionId: 'session-1',
    sessionTitle: '写周报',
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
    patCount: 0,
    bondDays: 1,
    activeSessions: 1,
    sessions: [],
    tasks: [],
    updatedAt: NOW,
  };
}

interface HttpResponse {
  status: number;
  headers: NodeJS.Dict<string | string[]>;
  body: string;
}

function call(
  port: number,
  path: string,
  options: { method?: string; token?: string; host?: string; headers?: Record<string, string> } = {},
): Promise<HttpResponse> {
  return new Promise((resolve, reject) => {
    const req = httpRequest(
      {
        host: '127.0.0.1',
        port,
        path,
        method: options.method ?? 'GET',
        headers: {
          ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
          ...(options.host ? { Host: options.host } : {}),
          ...(options.headers ?? {}),
        },
      },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk: string) => {
          body += chunk;
        });
        res.on('end', () => {
          resolve({ status: res.statusCode ?? 0, headers: res.headers, body });
        });
      },
    );
    req.on('error', reject);
    req.end();
  });
}

const dirs: string[] = [];
const servers: PetStatusServer[] = [];

function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'pet-api-'));
  dirs.push(dir);
  return dir;
}

function makeServer(dir: string, rateLimitPerMinute?: number): PetStatusServer {
  const server = new PetStatusServer({ userDataDir: dir, rateLimitPerMinute });
  server.update(snapshot(), { ...DEFAULT_PET_CONFIG, externalApi: true });
  servers.push(server);
  return server;
}

afterEach(() => {
  while (servers.length > 0) servers.pop()!.stop();
  while (dirs.length > 0) rmSync(dirs.pop()!, { recursive: true, force: true });
});

describe('isAuthorizedHeader', () => {
  it('accepts a matching bearer token and rejects everything else', () => {
    expect(isAuthorizedHeader('Bearer abc123', 'abc123')).toBe(true);
    expect(isAuthorizedHeader('bearer abc123', 'abc123')).toBe(true);
    expect(isAuthorizedHeader('Bearer wrong', 'abc123')).toBe(false);
    expect(isAuthorizedHeader('Basic abc123', 'abc123')).toBe(false);
    expect(isAuthorizedHeader('Bearer ', 'abc123')).toBe(false);
    expect(isAuthorizedHeader(undefined, 'abc123')).toBe(false);
    expect(isAuthorizedHeader('Bearer abc123', '')).toBe(false);
  });
});

describe('RateLimiter', () => {
  it('enforces a fixed 60s window', () => {
    let now = 0;
    const limiter = new RateLimiter(2, () => now);
    expect(limiter.take('ip')).toBe(true);
    expect(limiter.take('ip')).toBe(true);
    expect(limiter.take('ip')).toBe(false);
    now += 60_000;
    expect(limiter.take('ip')).toBe(true);
    expect(limiter.take('other')).toBe(true);
  });
});

describe('PetStatusServer', () => {
  it('writes a loopback token file and serves authorized GETs', async () => {
    const dir = tempDir();
    const server = makeServer(dir);
    expect(server.getInfo()).toEqual({ enabled: false, port: null });

    await server.start();
    const info = server.getInfo();
    expect(info.enabled).toBe(true);
    expect(info.port).toBeGreaterThan(0);
    const port = info.port!;

    const file = statusTokenFile(dir);
    const tokenFile = JSON.parse(readFileSync(file, 'utf8')) as {
      version: number;
      pid: number;
      port: number;
      token: string;
    };
    expect(tokenFile).toMatchObject({ version: 1, pid: process.pid, port });
    expect(tokenFile.token).toMatch(/^[a-f0-9]{64}$/);
    if (process.platform !== 'win32') {
      expect(statSync(file).mode & 0o777).toBe(0o600);
    }

    const health = await call(port, '/v1/health', { token: tokenFile.token });
    expect(health.status).toBe(200);
    expect(JSON.parse(health.body)).toMatchObject({ ok: true, version: 1 });
    expect(health.headers['content-security-policy']).toBe(
      "default-src 'none'; frame-ancestors 'none'",
    );

    const localhost = await call(port, '/v1/health', {
      token: tokenFile.token,
      host: `localhost:${port}`,
    });
    expect(localhost.status).toBe(200);

    const status = await call(port, '/v1/status', { token: tokenFile.token });
    expect(status.status).toBe(200);
    const payload = JSON.parse(status.body) as { action: string; pets: unknown[] };
    expect(payload.action).toBe('thinking');
    expect(payload.pets).toHaveLength(1);
    expect(status.headers['cache-control']).toBe('no-store');
  });

  it('rejects missing tokens, non-GET methods, bad hosts and unknown paths', async () => {
    const dir = tempDir();
    const server = makeServer(dir);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };

    expect((await call(port, '/v1/status')).status).toBe(401);
    expect((await call(port, '/v1/status', { token: 'wrong' })).status).toBe(401);
    expect((await call(port, '/v1/status', { method: 'POST', token: tokenFile.token })).status).toBe(
      405,
    );
    expect(
      (await call(port, '/v1/status', { token: tokenFile.token, host: 'evil.example' })).status,
    ).toBe(403);
    expect((await call(port, '/nope', { token: tokenFile.token })).status).toBe(404);
  });

  it('rate limits requests per client', async () => {
    const dir = tempDir();
    const server = makeServer(dir, 2);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };

    expect((await call(port, '/v1/health', { token: tokenFile.token })).status).toBe(200);
    expect((await call(port, '/v1/health', { token: tokenFile.token })).status).toBe(200);
    const limited = await call(port, '/v1/health', { token: tokenFile.token });
    expect(limited.status).toBe(429);
    expect(limited.headers['retry-after']).toBe('60');
  });

  it('does not let unauthenticated floods consume the authenticated quota', async () => {
    const dir = tempDir();
    const server = makeServer(dir, 2);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };

    for (let i = 0; i < 10; i++) {
      expect((await call(port, '/v1/health')).status).toBe(401);
    }
    expect((await call(port, '/v1/health')).status).toBe(429);
    // The authenticated bucket is untouched by the flood.
    expect((await call(port, '/v1/health', { token: tokenFile.token })).status).toBe(200);
    expect((await call(port, '/v1/health', { token: tokenFile.token })).status).toBe(200);
    expect((await call(port, '/v1/health', { token: tokenFile.token })).status).toBe(429);
  });

  it('rejects requests that try to send a body', async () => {
    const dir = tempDir();
    const server = makeServer(dir);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };

    const res = await call(port, '/v1/status', {
      token: tokenFile.token,
      headers: { 'Content-Length': '5' },
    });
    expect(res.status).toBe(400);
    expect(JSON.parse(res.body)).toEqual({ error: 'body_not_allowed' });
  });

  it('does not delete another instance token file on stop', async () => {
    const dir = tempDir();
    const first = makeServer(dir);
    await first.start();
    const second = makeServer(dir);
    await second.start();
    const secondToken = (JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string })
      .token;

    first.stop();
    const stillThere = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };
    expect(stillThere.token).toBe(secondToken);

    second.stop();
    expect(() => statSync(statusTokenFile(dir))).toThrow();
  });

  it('removes the token file and closes the port on stop', async () => {
    const dir = tempDir();
    const server = makeServer(dir);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };

    server.stop();
    expect(server.getInfo()).toEqual({ enabled: false, port: null });
    expect(() => statSync(statusTokenFile(dir))).toThrow();
    await expect(call(port, '/v1/health', { token: tokenFile.token })).rejects.toThrow();
  });

  it('returns 503 for /v1/status before the first snapshot update', async () => {
    const dir = tempDir();
    const server = new PetStatusServer({ userDataDir: dir });
    servers.push(server);
    await server.start();
    const port = server.getInfo().port!;
    const tokenFile = JSON.parse(readFileSync(statusTokenFile(dir), 'utf8')) as { token: string };
    const res = await call(port, '/v1/status', { token: tokenFile.token });
    expect(res.status).toBe(503);
  });
});
