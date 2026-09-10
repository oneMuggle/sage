import { isGithubConfig } from '../../../electron/update/providerConfig';

describe('providerConfig', () => {
  it('isGithubConfig narrows by type', () => {
    const cfg: any = { owner: 'o', repo: 'r', channelMap: {}, requireArtifactSignature: false };
    expect(isGithubConfig(cfg)).toBe(true);
    expect(isGithubConfig({ baseUrl: 'x' })).toBe(false);
  });
});
