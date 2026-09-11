// electron/update/__tests__/providers/github.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createGithubReleasesProvider } from '../../../../electron/update/providers/github';

const fetchMock = vi.fn();

describe('GitHubReleasesProvider', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    (global as unknown as { fetch: unknown }).fetch = fetchMock;
  });

  afterEach(() => {
    (global as unknown as { fetch: unknown }).fetch = originalFetch;
  });

  it('checkForStable fetches /releases/latest and normalises version', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        tag_name: 'v0.4.9',
        name: '0.4.9',
        published_at: '2026-09-10T00:00:00Z',
        body: 'notes',
        assets: [
          {
            id: 1,
            name: 'Sage-Setup-0.4.9.exe',
            size: 100,
            browser_download_url:
              'https://github.com/o/r/releases/download/v0.4.9/Sage-Setup-0.4.9.exe',
          },
        ],
      }),
    });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        channelMap: { stable: false, beta: true, alpha: true },
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('stable');
    expect(r?.version).toBe('0.4.9');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/releases/latest'),
      expect.any(Object),
    );
  });

  it('maps 401 to ProviderError with credential hint', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await expect(p.checkForUpdates('stable')).rejects.toThrow(/凭证/);
  });

  it('maps 404 to repository-not-found error', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'missing',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await expect(p.checkForUpdates('stable')).rejects.toThrow(/仓库不存在/);
  });

  it('uses /releases list when prerelease channel selected', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [
        {
          tag_name: 'v0.5.0-alpha.1',
          name: '0.5.0-alpha.1',
          published_at: '2026-09-10T00:00:00Z',
          prerelease: true,
          body: 'alpha notes',
          assets: [
            {
              id: 1,
              name: 'Sage-Setup-0.5.0-alpha.1.exe',
              size: 100,
              browser_download_url:
                'https://github.com/o/r/releases/download/v0.5.0-alpha.1/Sage-Setup.exe',
            },
          ],
        },
      ],
    });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        channelMap: { alpha: true },
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('alpha');
    expect(r?.version).toBe('0.5.0-alpha.1');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/releases(\?|$)/),
      expect.any(Object),
    );
  });

  it('returns ok from ping when repo HEAD responds 200', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ full_name: 'o/r' }),
    });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    const ping = await p.ping();
    expect(ping.ok).toBe(true);
    expect(ping.latencyMs).toBeGreaterThanOrEqual(0);
  });

  it('omits Authorization header when token absent', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        tag_name: 'v0.4.9',
        published_at: '2026-09-10T00:00:00Z',
        assets: [],
      }),
    });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        channelMap: { stable: true },
        requireArtifactSignature: false,
      },
    });
    await p.checkForUpdates('stable');
    const opts = fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(opts.headers.Authorization).toBeUndefined();
  });

  it('sends Bearer token when configured', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        tag_name: 'v0.4.9',
        published_at: '2026-09-10T00:00:00Z',
        assets: [],
      }),
    });
    const p = createGithubReleasesProvider({
      id: 'x',
      displayName: 'GH',
      config: {
        owner: 'o',
        repo: 'r',
        token: 'ghp_xxx',
        channelMap: { stable: true },
        requireArtifactSignature: false,
      },
    });
    await p.checkForUpdates('stable');
    const opts = fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(opts.headers.Authorization).toBe('Bearer ghp_xxx');
  });
});