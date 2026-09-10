// electron/update/__tests__/providers/registry.test.ts
import { describe, it, expect } from 'vitest';
import { ProviderRegistry } from '../../../../electron/update/providers/registry';
import type { UpdateProvider } from '../../../../electron/update/providers/base';

describe('ProviderRegistry', () => {
  it('registers and builds provider by type', () => {
    const reg = new ProviderRegistry();
    const fakeProvider: UpdateProvider = {
      type: 'github', id: 'x', displayName: 'x', channels: [],
      checkForUpdates: async () => null,
      downloadAsset: async () => '',
      ping: async () => ({ ok: true, latencyMs: 1 }),
    };
    reg.register('github', () => fakeProvider);
    const built = reg.build({
      id: 'a', type: 'github', displayName: 'x', enabled: true, isDefault: true,
      createdAt: '', updatedAt: '',
      config: { owner: 'o', repo: 'r', channelMap: {}, requireArtifactSignature: false },
    });
    expect(built.type).toBe('github');
  });

  it('throws on unregistered type', () => {
    const reg = new ProviderRegistry();
    expect(() => reg.build({
      id: 'a', type: 'gitee', displayName: 'x', enabled: true, isDefault: true,
      createdAt: '', updatedAt: '',
      config: { owner: 'o', repo: 'r', token: 't', channelMap: {}, requireArtifactSignature: false },
    })).toThrow(/No factory registered for type: gitee/);
  });
});
