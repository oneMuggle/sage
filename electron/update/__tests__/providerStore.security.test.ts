// electron/update/__tests__/providerStore.security.test.ts
import { vi, describe, it, expect, beforeEach } from 'vitest';
import Store from 'electron-store';
import { ProviderStore } from '../../../electron/update/providerStore';
import { logger } from '../../../electron/logger';

// mock electron-store with a `path` field (chmod uses store.path)
vi.mock('electron-store', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let data: any = {};
  const PATH = '/tmp/sage-update.json';
  class MockStore {
    path = PATH;
    get = (k: string) => data[k];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    set = (k: string, v: any) => {
      data[k] = v;
    };
    delete = (k: string) => {
      delete data[k];
    };
    _reset = () => {
      data = {};
    };
  }
  return { default: MockStore };
});

// mock fs.chmodSync to verify call without touching real filesystem
vi.mock('node:fs', async () => {
  const actual = await vi.importActual<typeof import('node:fs')>('node:fs');
  return {
    ...actual,
    existsSync: vi.fn(() => true),
    chmodSync: vi.fn(),
  };
});

// mock electron safeStorage (overridden per-test)
const isEncryptionAvailable = vi.fn(() => true);
const encryptString = (s: string) => Buffer.from('enc:' + s);
const decryptString = (b: Buffer) => b.toString().slice(4);
vi.mock('electron', () => ({
  safeStorage: {
    isEncryptionAvailable: () => isEncryptionAvailable(),
    encryptString: (s: string) => encryptString(s),
    decryptString: (b: Buffer) => decryptString(b),
  },
}));

// mock logger to spy on warn
vi.mock('../../../electron/logger', () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

describe('ProviderStore safeStorage degradation', () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const MockStore = Store as any;
    new MockStore()._reset();
    isEncryptionAvailable.mockReturnValue(true);
    vi.clearAllMocks();
  });

  it('keeps token plaintext + flags _tokenEncrypted=false when safeStorage unavailable', async () => {
    isEncryptionAvailable.mockReturnValue(false);
    const store = new ProviderStore();
    const id = await store.add({
      type: 'github',
      displayName: 'x',
      enabled: true,
      isDefault: true,
      config: {
        owner: 'o',
        repo: 'r',
        token: 'plain-token',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    const list = await store.list();
    const cfg = list.find((c) => c.id === id);
    expect(cfg).toBeDefined();
    expect(cfg?._tokenEncrypted).toBe(false);
    // The token stays as plaintext, but the cfg.config.token must still match.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((cfg?.config as any).token).toBe('plain-token');
  });

  it('logs warn once per process when degradation happens', async () => {
    // _degradationWarned is a module-level flag in providerStore.ts that
    // persists for the lifetime of the process. Earlier tests in this
    // file already triggered the degradation path, so we reset the module
    // graph and re-import ProviderStore to get a fresh flag.
    isEncryptionAvailable.mockReturnValue(false);
    vi.resetModules();
    const freshLogger = vi.hoisted(() => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }));
    vi.doMock('../../../electron/logger', () => ({ logger: freshLogger }));
    const { ProviderStore: FreshProviderStore } = await import(
      '../../../electron/update/providerStore'
    );
    const store = new FreshProviderStore();
    // First add triggers the warn
    await store.add({
      type: 'github',
      displayName: 'x',
      enabled: true,
      isDefault: true,
      config: {
        owner: 'o',
        repo: 'r',
        token: 't',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    // Second add should NOT re-warn
    await store.add({
      type: 'github',
      displayName: 'y',
      enabled: true,
      isDefault: false,
      config: {
        owner: 'o',
        repo: 'r',
        token: 't2',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(freshLogger.warn).toHaveBeenCalledTimes(1);
    expect(freshLogger.warn.mock.calls[0]?.[0]).toMatch(/safeStorage unavailable/);
  });

  it('chmod 0o600 on store file when degradation happens', async () => {
    isEncryptionAvailable.mockReturnValue(false);
    const fs = await import('node:fs');
    const chmodSync = vi.mocked(fs.chmodSync);
    const store = new ProviderStore();
    await store.add({
      type: 'github',
      displayName: 'x',
      enabled: true,
      isDefault: true,
      config: {
        owner: 'o',
        repo: 'r',
        token: 't',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(chmodSync).toHaveBeenCalledWith(expect.stringContaining('sage-update.json'), 0o600);
  });

  it('roundtrips encrypted token correctly when safeStorage is available', async () => {
    isEncryptionAvailable.mockReturnValue(true);
    const store = new ProviderStore();
    const id = await store.add({
      type: 'github',
      displayName: 'x',
      enabled: true,
      isDefault: true,
      config: {
        owner: 'o',
        repo: 'r',
        token: 'secret-abc',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    const cfg = await store.get(id);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((cfg?.config as any).token).toBe('secret-abc');
    expect(cfg?._tokenEncrypted).toBe(true);
  });

  it('does NOT log warn when safeStorage is available', async () => {
    isEncryptionAvailable.mockReturnValue(true);
    const warn = vi.mocked(logger.warn);
    const store = new ProviderStore();
    await store.add({
      type: 'github',
      displayName: 'x',
      enabled: true,
      isDefault: true,
      config: {
        owner: 'o',
        repo: 'r',
        token: 't',
        channelMap: {},
        requireArtifactSignature: false,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(warn).not.toHaveBeenCalled();
  });
});