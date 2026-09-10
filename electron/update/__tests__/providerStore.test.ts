// electron/update/__tests__/providerStore.test.ts
import { vi, describe, it, expect, beforeEach } from 'vitest';
import Store from 'electron-store';
import { ProviderStore } from '../../../electron/update/providerStore';

// mock electron-store
vi.mock('electron-store', () => {
  let data: any = {};
  class MockStore {
    get = (k: string) => data[k];
    set = (k: string, v: any) => { data[k] = v; };
    delete = (k: string) => { delete data[k]; };
    _reset = () => { data = {}; };
  }
  return { default: MockStore };
});
vi.mock('electron', () => ({
  safeStorage: { isEncryptionAvailable: () => true, encryptString: (s: string) => Buffer.from(s), decryptString: (b: Buffer) => b.toString() },
}));

describe('ProviderStore', () => {
  beforeEach(() => {
    const MockStore = Store as any;
    new MockStore()._reset();
  });

  it('add then list returns saved config with isDefault enforced unique', async () => {
    const store = new ProviderStore();
    await store.add({
      type: 'github', displayName: 'G1', enabled: true, isDefault: true,
      config: { owner: 'o', repo: 'r', token: 'ghp_xxx', channelMap: {}, requireArtifactSignature: false },
    } as any);
    await store.add({
      type: 'gitee', displayName: 'G2', enabled: true, isDefault: true,
      config: { owner: 'o', repo: 'r', token: 't', channelMap: {}, requireArtifactSignature: false },
    } as any);
    const list = await store.list();
    expect(list).toHaveLength(2);
    expect(list.find((c) => c.displayName === 'G1')?.isDefault).toBe(false);
    expect(list.find((c) => c.displayName === 'G2')?.isDefault).toBe(true);
  });
});