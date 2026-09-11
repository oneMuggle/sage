// electron/update/providers/gitee.ts
import type { UpdateProvider, NormalisedRelease, ProviderChannel } from './base';
import type { GiteeConfig } from '../providerConfig';
import { ProviderError } from './genericHttp';

const CHANNELS: ProviderChannel[] = [
  { id: 'stable', label: 'Stable', description: '正式版（pre=false）' },
  { id: 'beta', label: 'Beta', description: '预发布（pre=true）' },
  { id: 'alpha', label: 'Alpha', description: '预发布（pre=true）' },
];

export function createGiteeReleasesProvider(config: {
  id: string;
  displayName: string;
  config: GiteeConfig;
}): UpdateProvider {
  const { id, displayName, config: cfg } = config;
  // Gitee API v5 uses ?access_token=… for private repos.
  // Public repos also work without token but we always pass through cfg.token.
  const tokenParam = `access_token=${encodeURIComponent(cfg.token)}`;

  return {
    type: 'gitee',
    id,
    displayName,
    channels: CHANNELS,

    async checkForUpdates(channel, opts) {
      const wantPrerelease = cfg.channelMap[channel] ?? false;
      const base = wantPrerelease
        ? `https://gitee.com/api/v5/repos/${cfg.owner}/${cfg.repo}/releases?per_page=10&${tokenParam}`
        : `https://gitee.com/api/v5/repos/${cfg.owner}/${cfg.repo}/releases/latest?${tokenParam}`;
      const res = await fetch(base, { signal: opts?.signal });
      if (res.status === 401 || res.status === 403) {
        throw new ProviderError(`凭证无效（HTTP ${res.status}）`, res.status);
      }
      if (res.status === 404) {
        throw new ProviderError(`仓库不存在：${cfg.owner}/${cfg.repo}`, 404);
      }
      if (!res.ok) {
        throw new ProviderError(`Gitee 返回 HTTP ${res.status}`, res.status);
      }
      const data: unknown = await res.json();
      const release = wantPrerelease ? pickNewestPrerelease(data) : data;
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
          `https://gitee.com/api/v5/repos/${cfg.owner}/${cfg.repo}?${tokenParam}`,
          { signal: opts?.signal },
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

interface GiteeReleaseRaw {
  tag_name?: string;
  name?: string;
  published_at?: string;
  body?: string;
  prerelease?: boolean;
  assets?: Array<{
    id: number;
    name: string;
    size: number;
    browser_download_url: string;
  }>;
}

function pickNewestPrerelease(releases: unknown): GiteeReleaseRaw | null {
  if (!Array.isArray(releases)) return null;
  const candidates = releases.filter(
    (r): r is GiteeReleaseRaw =>
      typeof r === 'object' && r !== null && (r as GiteeReleaseRaw).prerelease === true,
  );
  candidates.sort((a, b) => {
    const ta = new Date(a.published_at ?? 0).getTime();
    const tb = new Date(b.published_at ?? 0).getTime();
    return tb - ta;
  });
  return candidates[0] ?? null;
}

function normalise(release: GiteeReleaseRaw, channel: string): NormalisedRelease {
  const platformKey =
    process.platform === 'win32'
      ? '.exe'
      : process.platform === 'darwin'
        ? '.dmg'
        : '.AppImage';
  const assets = (release.assets ?? [])
    .filter((a) => a.name.endsWith(platformKey) || a.name.includes('Setup'))
    .map((a) => ({
      id: String(a.id),
      name: a.name,
      size: a.size,
      downloadUrl: a.browser_download_url,
    }));
  return {
    version: (release.tag_name ?? release.name ?? '').replace(/^v/, ''),
    channel,
    publishedAt: release.published_at ?? '',
    releaseNotes: release.body,
    assets,
    raw: release,
  };
}