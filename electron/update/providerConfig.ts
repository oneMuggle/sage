// electron/update/providerConfig.ts
import type { ProviderType } from './providers/base';
export type { ProviderType };

export interface ProviderInstanceConfig {
  id: string;
  type: ProviderType;
  displayName: string;
  enabled: boolean;
  isDefault: boolean;
  createdAt: string;
  updatedAt: string;
  config: GithubConfig | GiteeConfig | GitlabConfig | GenericHttpConfig;
  /** Internal flag set by ProviderStore.encryptSensitive when the config.token
   *  has been encrypted via Electron safeStorage. Not part of user-facing schema. */
  _tokenEncrypted?: boolean;
}

export interface GithubConfig {
  owner: string;
  repo: string;
  token?: string;
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GiteeConfig {
  owner: string;
  repo: string;
  token: string;
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GitlabConfig {
  baseUrl: string;
  projectId: string | number;
  token: string;
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GenericHttpConfig {
  manifestUrl: string;
  publicKey: string;
  channelMap: Record<string, boolean>;
  requireArtifactSignature: true;
}

export const isGithubConfig = (c: unknown): c is GithubConfig => {
  const obj = c as Record<string, unknown> | null | undefined;
  return typeof obj?.owner === 'string' && typeof obj?.repo === 'string';
};

export const isGiteeConfig = (c: unknown): c is GiteeConfig => {
  const obj = c as Record<string, unknown> | null | undefined;
  return typeof obj?.token === 'string' && typeof obj?.owner === 'string';
};

export const isGitlabConfig = (c: unknown): c is GitlabConfig => {
  const obj = c as Record<string, unknown> | null | undefined;
  return typeof obj?.baseUrl === 'string' && typeof obj?.token === 'string';
};

export const isGenericHttpConfig = (c: unknown): c is GenericHttpConfig => {
  const obj = c as Record<string, unknown> | null | undefined;
  return typeof obj?.manifestUrl === 'string' && typeof obj?.publicKey === 'string';
};
