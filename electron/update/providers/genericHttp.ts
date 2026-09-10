// electron/update/providers/genericHttp.ts
import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import type { UpdateProvider, NormalisedRelease, ProviderChannel } from './base';
import type { GenericHttpConfig } from '../providerConfig';

const CHANNELS: ProviderChannel[] = [
  { id: 'stable', label: 'Stable', description: 'Production-ready releases' },
  { id: 'beta', label: 'Beta', description: 'Pre-release testing' },
  { id: 'alpha', label: 'Alpha', description: 'Internal early releases' },
];

export class ProviderError extends Error {
  constructor(
    message: string,
    public statusCode: number,
  ) {
    super(message);
    this.name = 'ProviderError';
  }
}

export function createGenericHttpProvider(config: {
  id: string;
  displayName: string;
  config: GenericHttpConfig;
}): UpdateProvider {
  const { id, displayName, config: cfg } = config;
  return {
    type: 'generic-http',
    id,
    displayName,
    channels: CHANNELS,

    async checkForUpdates(channel, opts) {
      const url = `${cfg.manifestUrl}?channel=${encodeURIComponent(channel)}`;
      const res = await fetch(url, { signal: opts?.signal });
      if (!res.ok) {
        throw new ProviderError(`Manifest fetch failed: HTTP ${res.status}`, res.status);
      }
      const json = await res.json();
      return json as NormalisedRelease;
    },

    async downloadAsset(release, assetId, opts) {
      const asset = release.assets.find((a) => a.id === assetId);
      if (!asset) throw new ProviderError(`Asset not found: ${assetId}`, 404);
      const url = new URL(asset.downloadUrl);
      if (url.hostname !== new URL(cfg.manifestUrl).hostname) {
        throw new ProviderError(`Untrusted download host: ${url.hostname}`, 0);
      }
      const res = await fetch(asset.downloadUrl, { signal: opts?.signal });
      if (!res.ok) throw new ProviderError(`Download failed: HTTP ${res.status}`, res.status);
      const buf = Buffer.from(await res.arrayBuffer());
      const path = `cache/sage-update-${release.version}.tmp`;
      await fs.mkdir('cache', { recursive: true });
      await fs.writeFile(path, buf);
      opts?.onProgress?.(buf.length, buf.length);
      return path;
    },

    async verifyArtifact(assetPath, signature, publicKey) {
      const data = await fs.readFile(assetPath);
      const verify = crypto.createVerify('RSA-SHA256');
      verify.update(data);
      return verify.verify(publicKey, Buffer.from(signature, 'base64'));
    },

    async ping(opts) {
      const start = Date.now();
      try {
        const res = await fetch(cfg.manifestUrl, { signal: opts?.signal, method: 'HEAD' });
        return { ok: res.ok, latencyMs: Date.now() - start };
      } catch (e: any) {
        return { ok: false, latencyMs: Date.now() - start, error: e.message };
      }
    },
  };
}
