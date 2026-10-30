// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  fetchSiteSessions,
  isHttpUrl,
  isLoginInProgressError,
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
});
