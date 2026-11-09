import { useEffect } from 'react';

/**
 * M2 (2026-11-09): 用户离开 Electron 窗口 ≥5 分钟且当前会话已有 ≥6 条消息时，
 * 自动触发一次 recap。复用 handleRecap 内部的 5 分钟节流，不会重复触发。
 *
 * 依赖 preload 的 `electronAPI.listen('app-focus', handler)`：
 * main 进程在 `win.on('focus')` 计算 awayMs 并发送 `sage:event:app-focus`。
 */
const RECAP_AWAY_THRESHOLD_MS = 5 * 60 * 1000;
const RECAP_MIN_MESSAGES = 6;

export function useRecapAutoTrigger({
  messageCount,
  onRecap,
}: {
  messageCount: number;
  onRecap: () => Promise<void> | void;
}) {
  useEffect(() => {
    const api = window.electronAPI;
    if (!api?.listen) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    api
      .listen<{ awayMs: number }>('app-focus', ({ awayMs }) => {
        if (awayMs >= RECAP_AWAY_THRESHOLD_MS && messageCount >= RECAP_MIN_MESSAGES) {
          void onRecap();
        }
      })
      .then((off) => {
        // listen() 是异步的：若组件在 promise settle 前卸载，立即退订，否则监听器泄漏。
        if (disposed) {
          off();
          return;
        }
        unlisten = off;
      });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [messageCount, onRecap]);
}
