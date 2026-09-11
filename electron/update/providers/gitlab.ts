// electron/update/providers/gitlab.ts
import type { UpdateProvider, NormalisedRelease, ProviderChannel } from './base';
import type { GitlabConfig } from '../providerConfig';
import { ProviderError } from './genericHttp';

const CHANNELS: ProviderChannel[] = [
  { id: 'stable', label: 'Stable', description: '正式版（upcoming_release=false）' },
  { id: 'beta', label: 'Beta', description: '预发布（upcoming_release=true）' },
  { id: 'alpha', label: 'Alpha', description: '预发布（upcoming_release=true）' },
];

export function createGitlabReleasesProvider(config: {
  id: string;
  displayName: string;
  config: GitlabConfig;
}): UpdateProvider {
  const { id, displayName, config: cfg } = config;
  // GitLab API v4 uses ?per_page=10 for the /releases list and the projectId may
  // be a numeric id OR a "namespace/project" path that must be URL-encoded.
  const projectSegment = encodeURIComponent(String(cfg.projectId));
  const headers: Record<string, string> = { 'PRIVATE-TOKEN': cfg.token };

  return {
    type: 'gitlab',
    id,
    displayName,
    channels: CHANNELS,

    async checkForUpdates(channel, opts) {
      const wantPrerelease = cfg.channelMap[channel] ?? false;
      const url = `${cfg.baseUrl.replace(/\/+$/, '')}/api/v4/projects/${projectSegment}/releases?per_page=10`;
      const res = await fetch(url, { headers, signal: opts?.signal });
      if (res.status === 401 || res.status === 403) {
        throw new ProviderError(`凭证无效（HTTP ${res.status}）`, res.status);
      }
      if (res.status === 404) {
        throw new ProviderError(`项目不存在：${cfg.projectId}`, 404);
      }
      if (!res.ok) {
        throw new ProviderError(`GitLab 返回 HTTP ${res.status}`, res.status);
      }
      const data: unknown = await res.json();
      const release = pickRelease(data, wantPrerelease);
      if (!release) return null;
      return normalise(release, channel);
    },

    async downloadAsset(release, assetId, opts) {
      const asset = release.assets.find((a) => a.id === assetId);
      if (!asset) throw new ProviderError(`Asset 不存在：${assetId}`, 404);
      const res = await fetch(asset.downloadUrl, { signal: opts?.signal });
      if (!res.ok) {
        throw new ProviderError(`下载失败 HTTP ${res.status}`, res.status);
      }
      const buf = Buffer.from(await res.arrayBuffer());
      const fs = await import('node:fs/promises');
      const path = `cache/sage-update-${release.version}.tmp`;
      await fs.mkdir('cache', { recursive: true });
      await fs.writeFile(path, buf);
      opts?.onProgress?.(buf.length, buf.length);
      return path;
    },

    async ping(opts) {
      const start = Date.now();
      try {
        const res = await fetch(
          `${cfg.baseUrl.replace(/\/+$/, '')}/api/v4/projects/${projectSegment}`,
          { headers, signal: opts?.signal },
        );
        return { ok: res.ok, latencyMs: Date.now() - start };
      } catch (e: unknown) {
        return {
          ok: false,
          latencyMs: Date.now() - start,
          error: e instanceof Error ? e.message : String(e),
        };
      }
    },
  };
}

interface GitlabReleaseRaw {
  tag_name?: string;
  name?: string;
  released_at?: string;
  description?: string;
  upcoming_release?: boolean;
  assets?: {
    count?: number;
    links?: Array<{
      id?: number;
      name?: string;
      url?: string;
      link_type?: string;
    }>;
  };
}

function pickRelease(data: unknown, wantPrerelease: boolean): GitlabReleaseRaw | null {
  if (!Array.isArray(data) || data.length === 0) return null;
  // GitLab marks upcoming releases (alphas/betas) with upcoming_release=true.
  // Stable channel → pick newest non-upcoming.
  // Prerelease channel → pick newest upcoming.
  const candidates = data
    .filter((r): r is GitlabReleaseRaw => typeof r === 'object' && r !== null)
    .filter((r) =>
      wantPrerelease ? r.upcoming_release === true : r.upcoming_release !== true,
    )
    .sort((a, b) => {
      const ta = new Date(a.released_at ?? 0).getTime();
      const tb = new Date(b.released_at ?? 0).getTime();
      return tb - ta;
    });
  return candidates[0] ?? null;
}

function normalise(release: GitlabReleaseRaw, channel: string): NormalisedRelease {
  const platformKey =
    process.platform === 'win32'
      ? '.exe'
      : process.platform === 'darwin'
        ? '.dmg'
        : '.AppImage';
  const links = release.assets?.links ?? [];
  const assets = links
    .filter((l) => {
      const n = l.name ?? '';
      return n.endsWith(platformKey) || n.includes('Setup');
    })
    .map((l) => ({
      id: String(l.id ?? l.url ?? ''),
      name: l.name ?? '',
      size: 0, // GitLab release link API does not return size in v4
      downloadUrl: l.url ?? '',
    }));
  return {
    version: (release.tag_name ?? release.name ?? '').replace(/^v/, ''),
    channel,
    publishedAt: release.released_at ?? '',
    releaseNotes: release.description,
    assets,
    raw: release,
  };
}