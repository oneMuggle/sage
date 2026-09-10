// electron/update/providers/base.ts
export type ProviderType = 'github' | 'gitee' | 'gitlab' | 'generic-http';

export interface ProviderChannel {
  id: string;
  label: string;
  description: string;
}

export interface NormalisedRelease {
  version: string;
  channel: string;
  publishedAt: string;
  releaseNotes?: string;
  assets: Array<{
    id: string;
    name: string;
    size: number;
    downloadUrl: string;
    checksum?: { algo: 'sha256' | 'sha512'; value: string };
    signature?: string;
  }>;
  raw?: unknown;
}

export interface UpdateProvider {
  readonly type: ProviderType;
  readonly id: string;
  readonly displayName: string;
  readonly channels: ProviderChannel[];
  checkForUpdates(channel: string, opts?: { signal?: AbortSignal }): Promise<NormalisedRelease | null>;
  downloadAsset(release: NormalisedRelease, assetId: string, opts?: {
    onProgress?: (bytes: number, total: number) => void;
    signal?: AbortSignal;
  }): Promise<string>;
  verifyArtifact?(assetPath: string, signature: string, publicKey: string): Promise<boolean>;
  ping(opts?: { signal?: AbortSignal }): Promise<{ ok: boolean; latencyMs: number; error?: string }>;
}