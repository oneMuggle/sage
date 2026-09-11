// electron/update/__tests__/providers/gitlab.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createGitlabReleasesProvider } from '../../../../electron/update/providers/gitlab';

const fetchMock = vi.fn();

describe('GitlabReleasesProvider', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    (global as unknown as { fetch: unknown }).fetch = fetchMock;
  });

  afterEach(() => {
    (global as unknown as { fetch: unknown }).fetch = originalFetch;
  });

  it('checkForStable fetches /releases with PRIVATE-TOKEN', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [
        {
          tag_name: 'v0.4.9',
          name: '0.4.9',
          released_at: '2026-09-10T00:00:00Z',
          description: 'notes',
          upcoming_release: false,
          assets: {
            count: 1,
            links: [
              {
                id: 1,
                name: 'Sage-Setup-0.4.9.exe',
                url: 'https://gitlab.com/o/r/-/jobs/1/artifacts/raw/Sage-Setup-0.4.9.exe',
                link_type: 'package',
              },
            ],
          },
        },
      ],
    });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.com',
        projectId: 42,
        token: 'glpat_xxx',
        channelMap: { stable: false, beta: true, alpha: true },
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('stable');
    expect(r?.version).toBe('0.4.9');
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain('https://gitlab.com/api/v4/projects/42/releases');
    const opts = fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(opts.headers['PRIVATE-TOKEN']).toBe('glpat_xxx');
  });

  it('URL-encodes string projectId', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.example.com',
        projectId: 'group/sub/project',
        token: 'tok',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await p.checkForUpdates('stable');
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain('projects/group%2Fsub%2Fproject/releases');
  });

  it('respects custom baseUrl (self-hosted)', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gl.internal.corp',
        projectId: 7,
        token: 'tok',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await p.checkForUpdates('stable');
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url.startsWith('https://gl.internal.corp/api/v4/projects/7/')).toBe(true);
  });

  it('maps 401 to credential error', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.com',
        projectId: 42,
        token: 'bad',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await expect(p.checkForUpdates('stable')).rejects.toThrow(/凭证/);
  });

  it('maps 404 to project-not-found error', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.com',
        projectId: 9999,
        token: 'tok',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    await expect(p.checkForUpdates('stable')).rejects.toThrow(/项目不存在/);
  });

  it('returns null when no releases exist', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => [] });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.com',
        projectId: 42,
        token: 'tok',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    const r = await p.checkForUpdates('stable');
    expect(r).toBeNull();
  });

  it('ping returns ok when project HEAD responds 200', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: 42, name: 'project' }),
    });
    const p = createGitlabReleasesProvider({
      id: 'x',
      displayName: 'GL',
      config: {
        baseUrl: 'https://gitlab.com',
        projectId: 42,
        token: 'tok',
        channelMap: {},
        requireArtifactSignature: false,
      },
    });
    const ping = await p.ping();
    expect(ping.ok).toBe(true);
  });
});