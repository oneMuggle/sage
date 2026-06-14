/**
 * Renderer-side IPC shim — invoke(cmd, args) → Electron main process → backend HTTP.
 *
 * 命名历史（2026-06-13）：
 * - 旧名 tauriInvoke（误导：实际委托 Electron，与 Tauri 无关）
 * - 新名 desktopInvoke（准确：桌面端 invoke，与 transport 解耦）
 *
 * 内部委托 `window.electronAPI.invoke`（preload.ts 通过 contextBridge 注入）
 * 主进程（electron/main.ts）再把 invoke 转成对 backend FastAPI 的 HTTP 调用
 *
 * 测试通过 `vi.mock('@/shared/api/desktopInvoke')` 桩化，与底层 transport 解耦
 */
import type { ElectronAPI } from '../../types/electron-api';

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  return api.invoke<T>(cmd, args ?? {});
}
