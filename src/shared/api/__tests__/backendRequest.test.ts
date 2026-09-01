import { afterEach, describe, expect, it, vi } from 'vitest';

import { BackendNotAvailableError, backendRequest } from '../backendRequest';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('backendRequest', () => {
  it('fails closed when window is unavailable', async () => {
    const fetchStub = vi.fn();
    vi.stubGlobal('fetch', fetchStub);
    vi.stubGlobal('window', undefined);

    await expect(backendRequest({ path: '/api/v1/private' })).rejects.toBeInstanceOf(
      BackendNotAvailableError,
    );
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it('fails closed when the Electron bridge is unavailable', async () => {
    const fetchStub = vi.fn();
    vi.stubGlobal('fetch', fetchStub);
    vi.stubGlobal('window', {});

    await expect(backendRequest({ path: '/api/v1/private' })).rejects.toBeInstanceOf(
      BackendNotAvailableError,
    );
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it('uses the Electron bridge without exposing a capability to the renderer', async () => {
    const bridge = vi.fn().mockResolvedValue({ ok: true });
    const request = { path: '/api/v1/private', method: 'GET' as const };
    vi.stubGlobal('window', { electronAPI: { backendRequest: bridge } });

    await expect(backendRequest(request)).resolves.toEqual({ ok: true });
    expect(bridge).toHaveBeenCalledWith(request);
    expect(bridge).toHaveBeenCalledTimes(1);
  });
});
