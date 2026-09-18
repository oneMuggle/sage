/**
 * P2 importedPacks：桥缺省（Web 通道）行为、descriptor 注册、
 * CSS style 标签幂等注入/移除、plan→commit→remove 状态流。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ImportedPetPack, PetImportPlan } from '../../../shared/types/electron-api';
import { getPetPack, listAllPacks, setImportedPacks } from '../builtinPacks';
import {
  isPetImportAvailable,
  syncPackStyles,
  toDescriptor,
  useImportedPacksStore,
  __resetImportedPacksBootstrapForTests,
} from '../importedPacks';

const pack: ImportedPetPack = {
  id: 'panda-01',
  name: '小熊猫',
  bodyClass: 'pet-body-panda-01',
  animations: { idle: 'panda-idle', thinking: 'panda-thinking' },
  cssText: '.pet-body-panda-01{width:9px}',
  installedAt: 1,
};

function fakeBridge(overrides: Partial<Record<string, ReturnType<typeof vi.fn>>> = {}) {
  return {
    listImports: vi.fn(async () => [pack]),
    planImport: vi.fn(async (): Promise<PetImportPlan | null> => ({
      ok: true,
      token: 'tok-1',
      manifest: pack,
      files: [{ path: 'pet.json', sizeBytes: 10 }],
      totalBytes: 10,
      conflict: false,
    })),
    commitImport: vi.fn(async () => ({ ok: true })),
    discardImport: vi.fn(async () => ({ ok: true })),
    removePack: vi.fn(async () => ({ ok: true })),
    ...overrides,
  };
}

beforeEach(() => {
  setImportedPacks([]);
  __resetImportedPacksBootstrapForTests();
  useImportedPacksStore.setState({ packs: [], pendingPlan: null, errors: [] });
  document.head.querySelectorAll('style[data-pet-pack]').forEach((el) => el.remove());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).electronAPI;
});

describe('toDescriptor / 注册表同路', () => {
  it('导入包注册后经 getPetPack / listAllPacks 与内置同路解析', () => {
    const descriptor = toDescriptor(pack);
    setImportedPacks([descriptor]);
    expect(getPetPack('panda-01').bodyClass).toBe('pet-body-panda-01');
    expect(listAllPacks().map((p) => p.id)).toContain('panda-01');
    // 未知 id 仍回退内置第一只
    expect(getPetPack('ghost').id).toBe('mint-blob');
  });
});

describe('syncPackStyles', () => {
  it('注入幂等，包消失时移除对应 style 标签', () => {
    syncPackStyles([pack]);
    syncPackStyles([pack]);
    expect(document.querySelectorAll('style[data-pet-pack]')).toHaveLength(1);
    expect(
      document.querySelector('style[data-pet-pack="panda-01"]')!.textContent,
    ).toContain('width:9px');
    syncPackStyles([]);
    expect(document.querySelectorAll('style[data-pet-pack]')).toHaveLength(0);
  });
});

describe('importedPacks store（无桥 = Web 通道）', () => {
  it('无 electronAPI.pet：不可导入，refresh/planImport 静默无操作', async () => {
    expect(isPetImportAvailable()).toBe(false);
    await useImportedPacksStore.getState().refresh();
    await useImportedPacksStore.getState().planImport();
    expect(useImportedPacksStore.getState().packs).toEqual([]);
    expect(useImportedPacksStore.getState().pendingPlan).toBeNull();
  });
});

describe('importedPacks store（有桥）', () => {
  it('refresh 填列表并注册 descriptor + 注入 CSS', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = { pet: fakeBridge() };
    await useImportedPacksStore.getState().refresh();
    expect(useImportedPacksStore.getState().packs.map((p) => p.id)).toEqual(['panda-01']);
    expect(getPetPack('panda-01').id).toBe('panda-01');
    expect(document.querySelector('style[data-pet-pack="panda-01"]')).not.toBeNull();
  });

  it('plan 校验失败 → errors 呈现；取消 → 无状态变化', async () => {
    const bridge = fakeBridge({
      planImport: vi.fn(async () => ({ ok: false, errors: ['缺 pet.json'] })),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = { pet: bridge };
    await useImportedPacksStore.getState().planImport();
    expect(useImportedPacksStore.getState().errors).toEqual(['缺 pet.json']);

    const cancel = fakeBridge({ planImport: vi.fn(async () => null) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = { pet: cancel };
    await useImportedPacksStore.getState().planImport();
    expect(useImportedPacksStore.getState()).toMatchObject({ pendingPlan: null, errors: [] });
  });

  it('commit 成功清 pendingPlan 并 refresh；remove 走桥后刷新', async () => {
    const bridge = fakeBridge();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = { pet: bridge };
    await useImportedPacksStore.getState().planImport();
    expect(useImportedPacksStore.getState().pendingPlan?.token).toBe('tok-1');
    await useImportedPacksStore.getState().commitPending(false);
    expect(useImportedPacksStore.getState().pendingPlan).toBeNull();
    expect(bridge.commitImport).toHaveBeenCalledWith('tok-1', false);
    expect(bridge.listImports).toHaveBeenCalledTimes(1);

    bridge.listImports.mockResolvedValueOnce([]);
    await useImportedPacksStore.getState().removePack('panda-01');
    expect(bridge.removePack).toHaveBeenCalledWith('panda-01');
    expect(useImportedPacksStore.getState().packs).toEqual([]);
    expect(document.querySelector('style[data-pet-pack="panda-01"]')).toBeNull();
  });
});
