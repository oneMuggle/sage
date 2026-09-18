// src/features/pet/importedPacks.ts
//
// P2 宠物包导入的渲染端入口：经 `window.electronAPI.pet` 桥读取/管理
// 主进程已入库的宠物包（zip 校验全在 electron/petImport.ts），把
// ImportedPetPack 转成与内置包同型的 PetPackDescriptor 注册进
// builtinPacks 解析表，并把包内 CSS 注入 <head>（每包一个 <style>，
// data-pet-pack=id 幂等对齐）。
//
// 非 Electron（Web 通道）无桥 → 列表为空、导入入口隐藏。

import { useEffect } from 'react';
import { create } from 'zustand';

import type { ImportedPetPack, PetImportPlan } from '../../shared/types/electron-api';

import type { PetPackDescriptor } from './builtinPacks';
import { setImportedPacks } from './builtinPacks';
import type { PetState } from './petStore';

function petBridge() {
  return typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;
}

/** Web 通道（无 Electron 桥）隐藏导入入口。 */
export function isPetImportAvailable(): boolean {
  return petBridge() !== undefined;
}

export function toDescriptor(pack: ImportedPetPack): PetPackDescriptor {
  const animations: Partial<Record<PetState, string>> = {};
  for (const [state, cls] of Object.entries(pack.animations)) {
    animations[state as PetState] = cls;
  }
  return {
    id: pack.id,
    name: pack.name,
    bodyClass: pack.bodyClass,
    animations,
  };
}

const STYLE_ATTR = 'data-pet-pack';

/** 注入/更新/移除包样式——以 packs 列表为唯一事实源，幂等对齐。 */
export function syncPackStyles(packs: readonly ImportedPetPack[]): void {
  if (typeof document === 'undefined') return;
  const alive = new Set(packs.map((p) => p.id));
  for (const el of Array.from(document.querySelectorAll(`style[${STYLE_ATTR}]`))) {
    if (!alive.has(el.getAttribute(STYLE_ATTR) ?? '')) el.remove();
  }
  for (const pack of packs) {
    let el = document.querySelector<HTMLStyleElement>(`style[${STYLE_ATTR}="${pack.id}"]`);
    if (!el) {
      el = document.createElement('style');
      el.setAttribute(STYLE_ATTR, pack.id);
      document.head.appendChild(el);
    }
    el.textContent = pack.cssText;
  }
}

interface ImportedPacksState {
  packs: ImportedPetPack[];
  /** plan 成功后的待确认导入（含冲突信息与 commit token） */
  pendingPlan: Extract<PetImportPlan, { ok: true }> | null;
  errors: string[];
  refresh: () => Promise<void>;
  planImport: () => Promise<void>;
  commitPending: (overwrite: boolean) => Promise<void>;
  discardPending: () => Promise<void>;
  removePack: (id: string) => Promise<void>;
}

export const useImportedPacksStore = create<ImportedPacksState>((set, get) => ({
  packs: [],
  pendingPlan: null,
  errors: [],

  refresh: async () => {
    const api = petBridge();
    if (!api) return;
    try {
      const packs = await api.listImports();
      set({ packs });
      setImportedPacks(packs.map(toDescriptor));
      syncPackStyles(packs);
    } catch (error) {
      set({ errors: [String(error)] });
    }
  },

  planImport: async () => {
    const api = petBridge();
    if (!api) return;
    set({ errors: [], pendingPlan: null });
    try {
      const plan = await api.planImport();
      if (!plan) return; // dialog 取消
      if (!plan.ok) {
        set({ errors: plan.errors });
        return;
      }
      const previous = get().pendingPlan;
      if (previous) await api.discardImport(previous.token);
      set({ pendingPlan: plan });
    } catch (error) {
      set({ errors: [String(error)] });
    }
  },

  commitPending: async (overwrite) => {
    const api = petBridge();
    const plan = get().pendingPlan;
    if (!api || !plan) return;
    const result = await api.commitImport(plan.token, overwrite);
    if (!result.ok) {
      set({ errors: [result.error ?? '入库失败'] });
      return;
    }
    set({ pendingPlan: null });
    await get().refresh();
  },

  discardPending: async () => {
    const api = petBridge();
    const plan = get().pendingPlan;
    if (!api || !plan) return;
    await api.discardImport(plan.token);
    set({ pendingPlan: null });
  },

  removePack: async (id) => {
    const api = petBridge();
    if (!api) return;
    const result = await api.removePack(id);
    if (!result.ok) {
      set({ errors: [result.error ?? '删除失败'] });
      return;
    }
    await get().refresh();
  },
}));

let bootstrapped = false;

/** 应用启动时（PetDock 挂载即触发）拉一次已导入包并注册。 */
export function useImportedPacksBootstrap(): void {
  const refresh = useImportedPacksStore((s) => s.refresh);
  useEffect(() => {
    if (bootstrapped || !isPetImportAvailable()) return;
    bootstrapped = true;
    void refresh();
  }, [refresh]);
}

/** 测试专用：重置一次性引导标记。 */
export function __resetImportedPacksBootstrapForTests(): void {
  bootstrapped = false;
}
