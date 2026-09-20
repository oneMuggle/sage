// src/features/right-panel/rightPanelStore.ts
//
// 右侧面板全局状态（right-panel R1 批次 A）——从 Chat.tsx 的 useState 与
// RightPanel 内部 useState 上抬。自动唤起（artifact_created → 面板打开）和
// 消息内联产物卡片（点击直达产物预览）都需要跨组件写面板状态，组件内
// useState 做不到，故全局化。
//
// 持久化沿用项目手工 localStorage 模式（无 persist 中间件用例）：
// - right-panel-open（旧值迁移：Chat.tsx 原键名不变，重启恢复开合）
// - right-panel-tab（R1 新增：重开面板回到上次 Tab）
// maximized / selectedArtifactId / seenArtifactCount 是会话级瞬时态，不持久化。

import { create } from 'zustand';

import { useStore } from '../../shared/lib/store';
import { useArtifactEventsStore } from '../artifacts/artifactEventsStore';

export type RightPanelTab = 'progress' | 'artifacts' | 'changes' | 'outline';

const TAB_KEY = 'right-panel-tab';
const OPEN_KEY = 'right-panel-open';

const VALID_TABS: readonly RightPanelTab[] = ['progress', 'artifacts', 'changes', 'outline'];

/** 产物创建时是否自动展开面板（Bell 开关写入；缺省 = 开）。 */
export function isArtifactAutoOpenEnabled(): boolean {
  try {
    return localStorage.getItem('right-panel-auto-open') !== '0';
  } catch {
    return true;
  }
}

export function setArtifactAutoOpenEnabled(enabled: boolean): void {
  try {
    localStorage.setItem('right-panel-auto-open', enabled ? '1' : '0');
  } catch {
    // localStorage 不可用（隐私模式等），静默容忍
  }
}

function loadInitialOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

function loadInitialTab(): RightPanelTab {
  try {
    const raw = localStorage.getItem(TAB_KEY) as RightPanelTab | null;
    if (raw && (VALID_TABS as readonly string[]).includes(raw)) return raw;
  } catch {
    // localStorage 不可用
  }
  return 'progress';
}

interface RightPanelState {
  open: boolean;
  tab: RightPanelTab;
  maximized: boolean;
  /** 当前在产物详情视图的 artifact id（RightPanel 按列表解析出对象） */
  selectedArtifactId: string | null;
  /** right-panel R5: 待在变更 Tab 打开的文件路径（ChangesSection 消费后清除） */
  selectedChangePath: string | null;
  /** 每会话"已见过的产物事件计数"基线（未读徽标 = counts - seen） */
  seenArtifactCount: Record<string, number>;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setTab: (tab: RightPanelTab) => void;
  setMaximized: (v: boolean) => void;
  /** 直达产物预览：开面板 + 切产物 Tab + 选中（内联卡片入口） */
  selectArtifact: (artifactId: string) => void;
  clearSelectedArtifact: () => void;
  /** right-panel R5: 直达变更 diff：开面板 + 切变更 Tab + 选中文件（内联卡片入口） */
  selectChange: (path: string) => void;
  clearSelectedChange: () => void;
  /** 面板打开时把当前会话的未读计数清零（读 artifactEventsStore 的计数作基线） */
  markArtifactsSeen: (sessionId: string) => void;
}

export const useRightPanelStore = create<RightPanelState>((set, get) => ({
  open: loadInitialOpen(),
  tab: loadInitialTab(),
  maximized: false,
  selectedArtifactId: null,
  selectedChangePath: null,
  seenArtifactCount: {},

  setOpen: (open) => {
    try {
      localStorage.setItem(OPEN_KEY, open ? '1' : '0');
    } catch {
      // localStorage 不可用
    }
    set({ open });
  },

  toggle: () => get().setOpen(!get().open),

  setTab: (tab) => {
    try {
      localStorage.setItem(TAB_KEY, tab);
    } catch {
      // localStorage 不可用
    }
    set({ tab });
  },

  setMaximized: (maximized) => set({ maximized }),

  selectArtifact: (artifactId) =>
    set({ open: true, tab: 'artifacts', selectedArtifactId: artifactId }),

  clearSelectedArtifact: () => set({ selectedArtifactId: null }),

  selectChange: (path) => set({ open: true, tab: 'changes', selectedChangePath: path }),

  clearSelectedChange: () => set({ selectedChangePath: null }),

  markArtifactsSeen: (sessionId) => {
    const counts = useArtifactEventsStore.getState().counts;
    set((prev) => ({
      seenArtifactCount: {
        ...prev.seenArtifactCount,
        [sessionId]: counts[sessionId] ?? 0,
      },
    }));
  },
}));

/**
 * artifact_created 到达时的自动唤起守卫（批次 B 从 orchestrationEvents 调用）：
 * 仅当事件属于当前正在查看的会话、自动展开开关打开、且面板当前关着时，
 * 才展开并落到产物 Tab。后台会话只 bump 计数（侧栏 📎N），不打扰当前视图。
 */
export function maybeAutoOpenArtifactPanel(sessionId: string): void {
  const state = useRightPanelStore.getState();
  if (state.open) return;
  if (useStore.getState().currentSessionId !== sessionId) return;
  if (!isArtifactAutoOpenEnabled()) return;
  state.setOpen(true);
  state.setTab('artifacts');
}
