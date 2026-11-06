// electron/notifyOverlay.ts
//
// 任务栏注意力提示（2026-11-05）。
//
// 后台会话等待审批 / 后台任务失败 / 完成时，除了 OS 通知，再给任务栏一个
// 信号：Windows/Linux 用 flashFrame 闪烁，macOS 用 dock badge 显示数字。
// 窗口重新聚焦时统一清除。
//
// 纯决策函数与副作用分离，便于单测。

import type { BrowserWindow } from 'electron';

export type TaskbarAttentionKind = 'awaiting_approval' | 'failed' | 'completed';

export interface TaskbarAttentionInput {
  awaitingApproval?: number;
  failed?: number;
  completed?: number;
}

export interface TaskbarAttentionState {
  count: number;
  kind: TaskbarAttentionKind | null;
}

/** 优先级：等待审批 > 失败 > 完成。 */
export function decideTaskbarAttention(input: TaskbarAttentionInput): TaskbarAttentionState {
  const approval = Math.max(0, Math.floor(input.awaitingApproval ?? 0));
  if (approval > 0) return { count: approval, kind: 'awaiting_approval' };
  const failed = Math.max(0, Math.floor(input.failed ?? 0));
  if (failed > 0) return { count: failed, kind: 'failed' };
  const completed = Math.max(0, Math.floor(input.completed ?? 0));
  if (completed > 0) return { count: completed, kind: 'completed' };
  return { count: 0, kind: null };
}

export interface ApplyTaskbarAttentionDeps {
  win: BrowserWindow | null;
  platform?: NodeJS.Platform;
  /** macOS dock badge 写入（注入以便单测） */
  setDockBadge?: (text: string) => void;
}

/** 把注意力状态落到窗口上；count<=0 时清除。 */
export function applyTaskbarAttention(
  state: TaskbarAttentionState,
  deps: ApplyTaskbarAttentionDeps,
): void {
  const { win, platform = process.platform, setDockBadge } = deps;
  if (!win || win.isDestroyed()) return;

  const clear = state.count <= 0 || state.kind === null;
  if (clear) {
    try {
      win.flashFrame(false);
    } catch {
      // 平台不支持时忽略
    }
    if (platform === 'darwin') setDockBadge?.('');
    return;
  }

  // 窗口在前台时不打扰；后台才闪烁。
  if (!win.isFocused()) {
    try {
      win.flashFrame(true);
    } catch {
      // 平台不支持时忽略
    }
  }
  if (platform === 'darwin') setDockBadge?.(String(state.count));
}
