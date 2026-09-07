// src/features/send-message/sessionNotify.ts
//
// S8 分会话 OS 通知 (对标增强第四轮批次 B, docs/plans/2026-09-07_coding-agent-parity-round4.md)。
// 渲染进程只做"该不该打扰"的判定与触发;原生 Notification 展示与点击
// 聚焦在 electron/main.ts ('sage:session:notify')。浏览器/dev 环境无桥
// 时全部 no-op,不抛错。

import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';

export interface SessionNotifyPayload {
  sessionId: string;
  title: string;
  body: string;
}

/** 触发 OS 通知（无 electron 桥时静默跳过） */
export function notifySession(payload: SessionNotifyPayload): void {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api?.notifySession) return;
  Promise.resolve(api.notifySession(payload)).catch(() => {
    /* 通知失败不影响主流程 */
  });
}

/**
 * 是否应该打扰用户：目标会话不是当前查看的会话，或窗口整体不可见。
 * 当前会话且窗口可见时不打扰（用户正盯着结果）。/btw 伪会话永不通知。
 */
export function shouldNotify(
  sessionId: string,
  currentSessionId: string | null | undefined,
): boolean {
  if (sessionId === '__btw__') return false;
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return true;
  return sessionId !== currentSessionId;
}

/** OS 通知点击 → 回调（主进程经 'sage:event:session-notify-click' 回发） */
export function onSessionNotifyClick(
  handler: (sessionId: string) => void,
): Promise<UnlistenFn | undefined> | undefined {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api?.listen) return undefined;
  return listen<{ sessionId: string }>('session-notify-click', ({ payload }) =>
    handler(payload.sessionId),
  ).catch(() => undefined);
}
