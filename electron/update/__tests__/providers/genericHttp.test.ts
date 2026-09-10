// electron/update/__tests__/providers/genericHttp.test.ts
import { vi, describe, it, expect } from 'vitest';
import { createGenericHttpProvider } from '../../../../electron/update/providers/genericHttp';
import type { GenericHttpConfig } from '../../../../electron/update/providerConfig';

// mock fetch
const fetchMock = vi.fn();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(global as any).fetch = fetchMock;

const baseCfg: GenericHttpConfig = {
  manifestUrl: 'https://updates.example.com/api/v1/updates/latest',
  publicKey: '-----BEGIN PUBLIC KEY-----\nMIIB...\n-----END PUBLIC KEY-----',
  channelMap: { stable: true, beta: true, alpha: true },
  requireArtifactSignature: true,
};

describe('GenericHttpProvider', () => {
  it('checkForUpdates fetches manifest and returns release', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        version: '0.4.9',
        channel: 'stable',
        publishedAt: '2026-09-10T00:00:00Z',
        assets: [{ id: 'a1', name: 'Sage.exe', size: 100, downloadUrl: 'https://updates.example.com/releases/0.4.9/Sage.exe' }],
      }),
    });
    const provider = createGenericHttpProvider({
      id: 'builtin',
      displayName: 'Official',
      config: baseCfg,
    });
    const release = await provider.checkForUpdates('stable');
    expect(release?.version).toBe('0.4.9');
  });
});
