/**
 * fetchStartupStatus 回归：/health/ready 轮询的解析与失败兜底。
 */
import { createServer, type Server } from 'node:http';

import { afterEach, describe, expect, it } from 'vitest';

import { fetchStartupStatus } from '../startupStatus';

async function listen(server: Server): Promise<number> {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address && typeof address === 'object') return address.port;
  throw new Error('server did not bind');
}

describe('fetchStartupStatus', () => {
  let server: Server | null = null;

  afterEach(() => {
    server?.close();
    server = null;
  });

  it('parses a /health/ready snapshot', async () => {
    const payload = {
      status: 'warming',
      phase: 'L1',
      boot_ms: 1234,
      modules: {
        database: { state: 'ready', layer: 1, elapsed_ms: 812, detail: null },
      },
      warmup: { done: 3, total: 15 },
    };
    server = createServer((_req, res) => {
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify(payload));
    });
    const port = await listen(server);

    const snapshot = await fetchStartupStatus(`http://127.0.0.1:${port}/health/ready`);
    expect(snapshot).toEqual(payload);
  });

  it('returns null on non-200 responses', async () => {
    server = createServer((_req, res) => {
      res.statusCode = 500;
      res.end('boom');
    });
    const port = await listen(server);

    expect(await fetchStartupStatus(`http://127.0.0.1:${port}/health/ready`)).toBeNull();
  });

  it('returns null when the connection fails', async () => {
    expect(await fetchStartupStatus('http://127.0.0.1:1/health/ready', 200)).toBeNull();
  });
});
