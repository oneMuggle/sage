// src/features/app-panels/usePanelStore.ts
//
// UX-IA R3 批次 A：统一槽位状态 + 一次性旧键迁移。
//
// 现状（docs/plans/2026-10-01_ux-ia-round3-panel-slot.md §1.2）：开合 / 宽度 / 高度
// 分散在 6 个 localStorage 键（right-panel-open / -width、terminal-panel-open /
// -height、sidebar-width），互斥关系无处安放。本 store 把它们收进**一个命名空间**
// `sage:panels:v1`，并把"互斥"变成 store 层规则：
//
//   1. 同槽位互斥：activate(right, 'wiki-inspector') 自动接管 right 槽位
//   2. 最大化独占：任一面最大化时，其它槽位的最大化态被清除（此前 z-40 浮层
//      盖在最大化右栏之上，就是没有这条规则的直接后果）
//   3. 尺寸夹取：所有写入口径统一走 clampSize(slot, n)
//
// 兼容：首次读入若无新键，则从旧键迁移并**删除旧键**（避免两处状态源）。
// localStorage 不可用（隐私模式/SSR）时静默降级到内存态，
// 与 rightPanelStore.ts:104-113 的容错写法一致。
import { create } from 'zustand';

import {
  clampSize,
  getPanelDefinition,
  PANEL_SLOT_IDS,
  slotGeometry,
  type PanelSlot,
} from './panelRegistry';

export const PANEL_STATE_KEY = 'sage:panels:v1';

/** 旧键 → 槽位。迁移成功后统一 removeItem，避免出现两个真相源。 */
const LEGACY_KEYS: readonly { key: string; slot: PanelSlot; read: (raw: string) => unknown }[] =
  [
    { key: 'right-panel-open', slot: 'right', read: (raw) => raw === '1' },
    { key: 'right-panel-width', slot: 'right', read: (raw) => Number(raw) },
    { key: 'terminal-panel-open', slot: 'bottom', read: (raw) => raw === '1' },
    { key: 'terminal-panel-height', slot: 'bottom', read: (raw) => Number(raw) },
    { key: 'sidebar-width', slot: 'left-list', read: (raw) => Number(raw) },
  ];

export interface PanelSlotState {
  open: boolean;
  /** 互斥槽位下当前激活的面；floating 等非互斥槽位为 null。 */
  active: string | null;
  size: number;
  maximized: boolean;
}

export type PanelSlotsState = Record<PanelSlot, PanelSlotState>;

function defaultSlotState(slot: PanelSlot): PanelSlotState {
  return {
    open: false,
    active: null,
    size: slotGeometry(slot).defaultSize,
    maximized: false,
  };
}

export function defaultPanelState(): PanelSlotsState {
  const base = {} as PanelSlotsState;
  for (const slot of PANEL_SLOT_IDS) base[slot] = defaultSlotState(slot);
  // 侧栏与任务中心在现状下始终可见，属迁移后的合理默认。
  base['left-rail'].open = true;
  base.floating.open = true;
  return base;
}

function readRaw(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRaw(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // localStorage 不可用
  }
}

function removeRaw(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // localStorage 不可用
  }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** 反序列化时逐槽位校验：脏字段回落默认，避免脏数据把面板卡在非法状态。 */
function sanitizeSlot(slot: PanelSlot, raw: unknown): PanelSlotState {
  const base = defaultSlotState(slot);
  if (!isPlainObject(raw)) return base;
  return {
    open: typeof raw.open === 'boolean' ? raw.open : base.open,
    active: typeof raw.active === 'string' ? raw.active : null,
    size: clampSize(slot, typeof raw.size === 'number' ? raw.size : base.size),
    maximized: slotGeometry(slot).maximizable && raw.maximized === true,
  };
}

/** 从旧键迁移。返回 null 表示无可迁移内容（全新用户 / 已被迁过）。 */
function migrateLegacy(): PanelSlotsState | null {
  const state = defaultPanelState();
  let migrated = false;

  for (const { key, slot, read } of LEGACY_KEYS) {
    const raw = readRaw(key);
    if (raw == null) continue;
    const value = read(raw);
    if (typeof value === 'boolean') {
      state[slot].open = value;
      migrated = true;
    } else if (typeof value === 'number' && Number.isFinite(value)) {
      state[slot].size = clampSize(slot, value);
      migrated = true;
    }
  }

  if (!migrated) return null;
  // 迁移成功后删除旧键：两处状态源并存必然漂移。
  for (const { key } of LEGACY_KEYS) removeRaw(key);
  return state;
}

function loadInitialState(): PanelSlotsState {
  const raw = readRaw(PANEL_STATE_KEY);
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (isPlainObject(parsed) && isPlainObject(parsed.slots)) {
        const base = defaultPanelState();
        for (const slot of PANEL_SLOT_IDS) {
          base[slot] = sanitizeSlot(slot, parsed.slots[slot]);
        }
        return base;
      }
    } catch {
      // JSON 损坏 → 落回迁移/默认值
    }
  }
  const migrated = migrateLegacy();
  if (migrated) {
    // 必须立刻落盘：migrateLegacy 已删掉旧键，若此时进程退出而新键未写，
    // 用户的面板尺寸会永久丢失（迁移变成破坏性操作）。
    persist(migrated);
    return migrated;
  }
  return defaultPanelState();
}

function persist(state: PanelSlotsState): void {
  writeRaw(PANEL_STATE_KEY, JSON.stringify({ v: 1, slots: state }));
}

export interface PanelState {
  slots: PanelSlotsState;
  /** 激活某面板：接管其槽位并打开。跨槽位互斥由 store 统一处理。 */
  activate: (id: string) => boolean;
  setOpen: (slot: PanelSlot, open: boolean) => void;
  toggle: (slot: PanelSlot) => void;
  setSize: (slot: PanelSlot, size: number) => void;
  setMaximized: (slot: PanelSlot, maximized: boolean) => void;
}

export const usePanelStore = create<PanelState>((set, get) => ({
  slots: loadInitialState(),

  activate: (id) => {
    const def = getPanelDefinition(id);
    // 未登记的面一律拒绝：新增面板必须先在 panelRegistry 登记，
    // 否则它的开合/尺寸无处持久化，会退化成又一个游离的 localStorage 键。
    if (!def) return false;

    set((prev) => {
      const next: PanelSlotsState = { ...prev.slots };
      const target = { ...next[def.slot], active: id, open: true };

      // 最大化占满主内容区：任何槽位进入最大化时，清掉其它槽位的最大化态，
      // 否则浮层（floating）与底部栏会盖在最大化面板之上。
      if (target.maximized) {
        for (const slot of PANEL_SLOT_IDS) {
          if (slot !== def.slot && next[slot].maximized) {
            next[slot] = { ...next[slot], maximized: false };
          }
        }
      }

      next[def.slot] = target;
      persist(next);
      return { slots: next };
    });
    return true;
  },

  setOpen: (slot, open) =>
    set((prev) => {
      const next = {
        ...prev.slots,
        [slot]: { ...prev.slots[slot], open, maximized: open ? prev.slots[slot].maximized : false },
      };
      persist(next);
      return { slots: next };
    }),

  toggle: (slot) => {
    get().setOpen(slot, !get().slots[slot].open);
  },

  setSize: (slot, size) =>
    set((prev) => {
      const next = {
        ...prev.slots,
        [slot]: { ...prev.slots[slot], size: clampSize(slot, size) },
      };
      persist(next);
      return { slots: next };
    }),

  setMaximized: (slot, maximized) =>
    set((prev) => {
      if (!slotGeometry(slot).maximizable) return prev;
      const next: PanelSlotsState = { ...prev.slots };
      if (maximized) {
        for (const s of PANEL_SLOT_IDS) {
          if (s !== slot && next[s].maximized) next[s] = { ...next[s], maximized: false };
        }
      }
      next[slot] = { ...prev.slots[slot], maximized, open: maximized ? true : prev.slots[slot].open };
      persist(next);
      return { slots: next };
    }),
}));
