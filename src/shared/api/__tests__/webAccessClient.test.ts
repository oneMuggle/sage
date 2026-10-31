// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createBrowserExtensionPairingCode,
  fetchBrowserExtensionStatus,
  fetchSiteSessions,
  isHttpUrl,
  isLoginInProgressError,
  revokeBrowserExtensionDevice,
  waitForSiteLogin,
} from '../webAccessClient';

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('webAccessClient', () => {
  it('validates http(s) URLs only', () => {
    expect(isHttpUrl('https://kns.cnki.net/')).toBe(true);
    expect(isHttpUrl('http://example.com')).toBe(true);
    expect(isHttpUrl('file:///etc/passwd')).toBe(false);
    expect(isHttpUrl('javascript:alert(1)')).toBe(false);
  });

  it('polls a login job until success', async () => {
    const statuses = ['running', 'running', 'success'];
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        job_id: 'j1',
        url: 'https://kns.cnki.net/',
        status: statuses.shift(),
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const job = await waitForSiteLogin('j1', { intervalMs: 1 });
    expect(job.status).toBe('success');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('reports failure status from the backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ job_id: 'j1', url: 'https://a.example', status: 'failed', error: 'nope' }),
      ),
    );
    const job = await waitForSiteLogin('j1', { intervalMs: 1 });
    expect(job.status).toBe('failed');
    expect(job.error).toBe('nope');
  });

  it('times out when the job never finishes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ job_id: 'j1', url: 'https://a.example', status: 'running' })),
    );
    await expect(
      waitForSiteLogin('j1', { intervalMs: 20, timeoutMs: 30 }),
    ).rejects.toThrow('login_timeout');
  });

  it('detects the 409 login_in_progress error text', () => {
    expect(
      isLoginInProgressError(
        new Error('Backend request failed: 409 {"ok":false,"error":"login_in_progress"}'),
      ),
    ).toBe(true);
    expect(isLoginInProgressError(new Error('other'))).toBe(false);
  });

  it('fetches masked site sessions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ sites: [{ domain: '.cnki.net', display_name: '知网' }] })),
    );
    const sites = await fetchSiteSessions();
    expect(sites[0].domain).toBe('.cnki.net');
  });

  it('fetches browser extension status without token material', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({
          devices: [
            {
              device_id: 'dev_1',
              label: 'Chrome',
              created_at: 1793500000,
              last_seen_at: 1793500100,
              connected: true,
              sharing: false,
            },
          ],
          connected: true,
          shared: null,
          base_url: 'http://127.0.0.1:8765',
          extension_dir: '/repo/extension/agent-bridge',
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const status = await fetchBrowserExtensionStatus();
    expect(status.devices[0].device_id).toBe('dev_1');
    expect(status.devices[0].connected).toBe(true);
    expect(status.shared).toBeNull();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/api/v1/web-access/browser-extension/status',
    );
    expect(JSON.stringify(status)).not.toContain('token');
  });

  it('creates a pairing code with POST', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({
          code: 'ABCDE23456',
          expires_at: 1793500300,
          base_url: 'http://127.0.0.1:8834',
          extension_dir: null,
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await createBrowserExtensionPairingCode();
    expect(result.code).toBe('ABCDE23456');
    expect(result.base_url).toBe('http://127.0.0.1:8834');
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe('POST');
  });

  it('revokes a device with an encoded id', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ ok: true }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await revokeBrowserExtensionDevice('dev/1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/browser-extension/devices/dev%2F1');
    expect(init?.method).toBe('DELETE');
  });
});
