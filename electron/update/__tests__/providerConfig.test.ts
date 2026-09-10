import { describe, it, expect } from 'vitest';
import { isGithubConfig } from '../../../electron/update/providerConfig';

describe('providerConfig', () => {
  it('isGithubConfig narrows by type', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cfg: any = { owner: 'o', repo: 'r', channelMap: {}, requireArtifactSignature: false };
    expect(isGithubConfig(cfg)).toBe(true);
    expect(isGithubConfig({ baseUrl: 'x' })).toBe(false);
  });
});
