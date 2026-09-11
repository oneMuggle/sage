// electron/update/__tests__/providers/gitee.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createGiteeReleasesProvider } from '../../../../electron/update/providers/gitee';

const fetchMock = vi.fn();

describe('GiteeReleasesProvider', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    (global as unknown as { fetch: unknown }).fetch = fetchMock;
  });

  afterEach(() => {
    (global as unknown as { fetch: unknown }).fetch = originalFetch;
  });

  it('checkForStable fetches /releases/latest with access_token query', async () => {
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
              'https://gitee.com/o/r/releases/download/v0.4.9/Sage-Setup-0.4.9.exe',
          },
        ],
      }),
    });
    const p = createGiteeReleasesProvider({
      id: 'x',
      displayName: 'GE',
      config: {
        owner: 'o',
        repo: 'r',
        token: 'gt_xxx',
        channelMap: { stable: false, beta: true, alpha: true },
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('stable');
    expect(r?.version).toBe('0.4.9');
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain('/releases/latest');
    expect(url).toContain('access_token=gt_xxx');
  });

  it('maps 401 to credential error', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
    const p = createGiteeReleasesProvider({
      id: 'x',
      displayName: 'GE',
      config: {
        owner: 'o',
        repo: 'r',
        token: 'bad',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await expect(p.checkForUpdates('stable')).rejects.toThrow(/凭证/);
  });

  it('returns prerelease from list when alpha channel selected', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [
        {
          tag_name: 'v0.5.0-alpha.1',
          name: '0.5.0-alpha.1',
          published_at: '2026-09-10T00:00:00Z',
          prerelease: true,
          body: 'alpha',
          assets: [
            {
              id: 1,
              name: 'Sage-Setup-0.5.0-alpha.1.exe',
              size: 100,
              browser_download_url:
                'https://gitee.com/o/r/releases/download/v0.5.0-alpha.1/Sage-Setup.exe',
            },
          ],
        },
      ],
    });
    const p = createGiteeReleasesProvider({
      id: 'x',
      displayName: 'GE',
      config: {
        owner: 'o',
        repo: 'r',
        token: 'gt',
        channelMap: { alpha: true },
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('alpha');
    expect(r?.version).toBe('0.5.0-alpha.1');
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain('/releases?');
    expect(url).toContain('access_token=gt');
  });

  it('ping returns ok when repo HEAD responds 200', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ full_name: 'o/r' }),
    });
    const p = createGiteeReleasesProvider({
      id: 'x',
      displayName: 'GE',
      config: {
        owner: 'o',
        repo: 'r',
        token: 'gt',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    const ping = await p.ping();
    expect(ping.ok).toBe(true);
  });
});