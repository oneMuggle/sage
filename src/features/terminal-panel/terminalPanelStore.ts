// src/features/terminal-panel/terminalPanelStore.ts
//
// Phase 3 (2026-09-25): 底部终端面板全局状态。
// ZCode 启发的 VS Code 风格底部终端面板 —— 管理面板开合、高度、当前 PTY 会话 id。
//
// 持久化：open / height 持久化到 localStorage（与 rightPanelStore 手工模式一致）；
// ptyId / ptyError 是会话级瞬时态（进程 id 每次启动都不同），不持久化。

import { create } from 'zustand';

const OPEN_KEY = 'terminal-panel-open';
const HEIGHT_KEY = 'terminal-panel-height';

const DEFAULT_HEIGHT = 240;
const MIN_HEIGHT = 120;
const MAX_HEIGHT = 600;

function loadInitialOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

function loadInitialHeight(): number {
  try {
    const raw = localStorage.getItem(HEIGHT_KEY);
    if (raw) {
      const n = Number(raw);
      if (Number.isFinite(n) && n >= MIN_HEIGHT && n <= MAX_HEIGHT) return n;
    }
  } catch {
    // localStorage 不可用
  }
  return DEFAULT_HEIGHT;
}

interface TerminalPanelState {
  open: boolean;
  height: number;
  /** 当前活跃的 PTY 进程 id（pty:create 返回）；null 表示尚未创建或已退出 */
  ptyId: string | null;
  /** 最后一次 pty:create 失败的原因（如 node-pty 未安装），null 表示无错误 */
  ptyError: string | null;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setHeight: (height: number) => void;
  setPtyId: (id: string | null) => void;
  setPtyError: (error: string | null) => void;
  clearPty: () => void;
}

export const useTerminalPanelStore = create<TerminalPanelState>((set, get) => ({
  open: loadInitialOpen(),
  height: loadInitialHeight(),
  ptyId: null,
  ptyError: null,

  setOpen: (open) => {
    try {
      localStorage.setItem(OPEN_KEY, open ? '1' : '0');
    } catch {
      // localStorage 不可用
    }
    set({ open });
  },

  toggle: () => get().setOpen(!get().open),

  setHeight: (height) => {
    const clamped = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, height));
    try {
      localStorage.setItem(HEIGHT_KEY, String(clamped));
    } catch {
      // localStorage 不可用
    }
    set({ height: clamped });
  },

  setPtyId: (id) => set({ ptyId: id, ptyError: null }),

  setPtyError: (error) => set({ ptyError: error }),

  clearPty: () => set({ ptyId: null }),
}));

export { MIN_HEIGHT, MAX_HEIGHT, DEFAULT_HEIGHT };
