/**
 * Progressive readiness（渲染层）。
 *
 * 双通道读取后端 `/health/ready` 快照：
 * - `getBackendStartupStatus()` 初始快照 —— 挂载时事件可能已经发过；
 * - `backend:startup-status` 事件 —— 主进程 ready 后 1s 间隔广播。
 *
 * Web 模式 / 测试环境无 electronAPI 桥时全部返回 null / no-op。
 */
import type { StartupStatusSnapshot } from '../types/electron-api';

export type { StartupStatusModule, StartupStatusSnapshot } from '../types/electron-api';

const STARTUP_STATUS_EVENT = 'backend:startup-status';

export async function fetchStartupStatusSnapshot(): Promise<StartupStatusSnapshot | null> {
  try {
    const snapshot = await window.electronAPI?.getBackendStartupStatus?.();
    return (snapshot as StartupStatusSnapshot | null | undefined) ?? null;
  } catch {
    return null;
  }
}

export async function subscribeStartupStatus(
  handler: (snapshot: StartupStatusSnapshot) => void,
): Promise<() => void> {
  const api = window.electronAPI;
  if (!api?.listen) return () => undefined;
  return api.listen<StartupStatusSnapshot>(STARTUP_STATUS_EVENT, (payload) => {
    if (payload && typeof payload === 'object') handler(payload);
  });
}
