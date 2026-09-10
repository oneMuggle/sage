// electron/update/providerConfig.ts
import { ProviderType } from './providers/base';

export interface ProviderInstanceConfig {
  id: string;
  type: ProviderType;
  displayName: string;
  enabled: boolean;
  isDefault: boolean;
  createdAt: string;
  updatedAt: string;
  config: GithubConfig | GiteeConfig | GitlabConfig | GenericHttpConfig;
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

export const isGithubConfig = (c: any): c is GithubConfig =>
  typeof c?.owner === 'string' && typeof c?.repo === 'string';

export const isGiteeConfig = (c: any): c is GiteeConfig =>
  typeof c?.token === 'string' && typeof c?.owner === 'string';

export const isGitlabConfig = (c: any): c is GitlabConfig =>
  typeof c?.baseUrl === 'string' && typeof c?.token === 'string';

export const isGenericHttpConfig = (c: any): c is GenericHttpConfig =>
  typeof c?.manifestUrl === 'string' && typeof c?.publicKey === 'string';
