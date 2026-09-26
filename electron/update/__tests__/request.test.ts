import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchUpdate } from '../request';

const fetchMock = vi.fn();
vi.mock('../../fetchCompat', () => ({ fetchCompat: (...args: unknown[]) => fetchMock(...args) }));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  fetchMock.mockReset();
});

describe('update-only offline boundary', () => {
  it.each(['offline', 'typo'])('denies %s before sending any request', async (mode) => {
    vi.stubEnv('SAGE_DEPLOYMENT_MODE', mode);
    await expect(fetchUpdate('https://updates.sage.app/')).rejects.toThrow(/offline/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('enforces exact HTTPS origin and disables redirects in intranet mode', async () => {
    vi.stubEnv('SAGE_DEPLOYMENT_MODE', 'intranet');
    vi.stubEnv('SAGE_UPDATE_ALLOWED_ORIGINS', 'https://updates.corp.example:8443');
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ version: '1' }) });
    await expect(fetchUpdate('https://updates.corp.example/')).rejects.toThrow(/approved/);
    await expect(fetchUpdate('http://updates.corp.example:8443/')).rejects.toThrow(/approved/);
    await expect(fetchUpdate('https://u:p@updates.corp.example:8443/')).rejects.toThrow(/approved/);
    const response = await fetchUpdate('https://updates.corp.example:8443/manifest');
    expect(await response.json()).toEqual({ version: '1' });
    expect(fetchMock.mock.calls[0][1].redirect).toBe('error');
  });

  it('denies missing or invalid enterprise origins', async () => {
    vi.stubEnv('SAGE_DEPLOYMENT_MODE', 'intranet');
    vi.stubEnv('SAGE_UPDATE_ALLOWED_ORIGINS', '');
    await expect(fetchUpdate('https://public.example/')).rejects.toThrow(/approved/);
    vi.stubEnv('SAGE_UPDATE_ALLOWED_ORIGINS', 'https://public.example/not-an-origin');
    await expect(fetchUpdate('https://public.example/')).rejects.toThrow(/Invalid/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('bounds a transport that ignores abort', async () => {
    vi.useFakeTimers();
    fetchMock.mockReturnValue(new Promise(() => {}));
    const pending = expect(fetchUpdate('https://updates.example/', {}, 50)).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(51);
    await pending;
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it('bounds body consumption as well as response headers', async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue({ ok: true, arrayBuffer: () => new Promise(() => {}) });
    const response = await fetchUpdate('https://updates.example/', {}, 50);
    const pending = expect(response.arrayBuffer()).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(51);
    await pending;
  });

  it('propagates caller cancellation and rejects pre-aborted signals without fetch', async () => {
    const controller = new AbortController();
    fetchMock.mockReturnValue(new Promise(() => {}));
    const pending = expect(fetchUpdate('https://updates.example/', { signal: controller.signal })).rejects.toThrow(/cancelled/);
    controller.abort();
    await pending;
    fetchMock.mockClear();
    await expect(fetchUpdate('https://updates.example/', { signal: controller.signal })).rejects.toThrow(/cancelled/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
