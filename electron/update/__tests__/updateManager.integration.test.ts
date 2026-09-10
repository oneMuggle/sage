// electron/update/__tests__/updateManager.integration.test.ts
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock electron-store: vitest ESM default-export semantics require
// returning `{ default: MockStore }` rather than the class directly
// (Task 1.5 lesson).
vi.mock('electron-store', () => {
  const data: Record<string, unknown> = {};
  class MockStore {
    get = (k: string) => data[k];
    set = (k: string, v: unknown) => {
      data[k] = v;
    };
    delete = (k: string) => {
      delete data[k];
    };
    _reset = () => {
      for (const k of Object.keys(data)) delete data[k];
    };
  }
  return { default: MockStore };
});

// Mock electron so the store + UpdateManager can import it under jsdom.
vi.mock('electron', () => ({
  safeStorage: { isEncryptionAvailable: () => false },
  app: { isPackaged: false, getPath: () => '/tmp', getVersion: () => '1.0.0' },
  ipcMain: { handle: () => {} },
}));

// Mock electron-updater so importing `autoUpdater` does not eagerly
// construct the native AppUpdater (which needs electron.app.getVersion).
// The provider code path never touches `autoUpdater`, but the constructor
// still references it in its `??` fallback.
vi.mock('electron-updater', () => ({
  autoUpdater: {},
}));

// Import after mocks so the SUT sees the mocked modules.
import { UpdateManager } from '../../../electron/updateManager';
import { ProviderRegistry } from '../../../electron/update/providers/registry';
import { ProviderStore } from '../../../electron/update/providerStore';
import { createGenericHttpProvider } from '../../../electron/update/providers/genericHttp';
import { BUILTIN_GENERIC_CONFIG } from '../../../electron/update/featureFlag';
import Store from 'electron-store';

function resetStore(): void {
  const MockStore = Store as unknown as { new (): { _reset: () => void } };
  new MockStore()._reset();
}

describe('UpdateManager integration with provider', () => {
  beforeEach(() => {
    resetStore();
  });

  it('init falls back to built-in Generic when no user provider is configured', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    registry.register('generic-http', (cfg) =>
      createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      }),
    );
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    // activeProvider should be the built-in generic-http fallback
    const ap = (mgr as unknown as { activeProvider: { type: string } | null }).activeProvider;
    expect(ap).toBeTruthy();
    expect(ap!.type).toBe('generic-http');
  });

  it('init uses the user-configured default provider when one is present', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    let builtId = '';
    registry.register('generic-http', (cfg) => {
      builtId = cfg.id;
      return createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      });
    });
    const userId = await store.add({
      type: 'generic-http',
      displayName: 'My Provider',
      enabled: true,
      isDefault: true,
      config: {
        manifestUrl: 'https://example.com/manifest',
        publicKey: BUILTIN_GENERIC_CONFIG.config.publicKey,
        channelMap: { stable: true },
        requireArtifactSignature: true as const,
      },
    });
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    const ap = (mgr as unknown as { activeProvider: { id: string; displayName: string } | null })
      .activeProvider;
    expect(ap).toBeTruthy();
    expect(ap!.id).toBe(userId);
    expect(builtId).toBe(userId);
    expect(ap!.displayName).toBe('My Provider');
  });

  it('switchProvider throws when target id is not found', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    registry.register('generic-http', (cfg) =>
      createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      }),
    );
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    await expect(mgr.switchProvider('does-not-exist')).rejects.toThrow(/not found/i);
  });

  it('switchProvider demotes previous default and promotes target', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    registry.register('generic-http', (cfg) =>
      createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      }),
    );
    const firstId = await store.add({
      type: 'generic-http',
      displayName: 'First',
      enabled: true,
      isDefault: true,
      config: {
        manifestUrl: 'https://example.com/manifest',
        publicKey: BUILTIN_GENERIC_CONFIG.config.publicKey,
        channelMap: { stable: true },
        requireArtifactSignature: true as const,
      },
    });
    const secondId = await store.add({
      type: 'generic-http',
      displayName: 'Second',
      enabled: true,
      isDefault: false,
      config: {
        manifestUrl: 'https://example.com/manifest',
        publicKey: BUILTIN_GENERIC_CONFIG.config.publicKey,
        channelMap: { stable: true },
        requireArtifactSignature: true as const,
      },
    });
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    expect((mgr as unknown as { activeProvider: { id: string } }).activeProvider.id).toBe(firstId);
    await mgr.switchProvider(secondId);
    expect((mgr as unknown as { activeProvider: { id: string } }).activeProvider.id).toBe(secondId);
    const list = await store.list();
    expect(list.find((c) => c.id === firstId)?.isDefault).toBe(false);
    expect(list.find((c) => c.id === secondId)?.isDefault).toBe(true);
  });

  it('pingProvider throws when target id is not found', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    registry.register('generic-http', (cfg) =>
      createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      }),
    );
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    await expect(mgr.pingProvider('missing')).rejects.toThrow(/not found/i);
  });

  it('checkWithProvider throws when target id is not found', async () => {
    const store = new ProviderStore();
    const registry = new ProviderRegistry();
    registry.register('generic-http', (cfg) =>
      createGenericHttpProvider({
        id: cfg.id,
        displayName: cfg.displayName,
        config: cfg.config as Parameters<typeof createGenericHttpProvider>[0]['config'],
      }),
    );
    const mgr = new UpdateManager({ providerStore: store, providerRegistry: registry });
    await mgr.init();
    await expect(mgr.checkWithProvider('missing')).rejects.toThrow(/not found/i);
  });
});