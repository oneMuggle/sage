/**
 * Renderer-side IPC shim — listen(event, handler) → Electron main → backend NDJSON stream.
 *
 * 命名历史（2026-06-13）：本文件保留 `tauriEvent` 名字（避免大改 import 路径），
 * 但内部实现已从 re-export `@tauri-apps/api/event` 切换为委托 `window.electronAPI.listen`。
 * 6 个月后（2026-12-31）正式改名为 `desktopEvent.ts`（见 Plan C）。
 *
 * 现状（2026-06-13 main + release/win7 统一栈）：
 * - shim 暴露的 listen 回调签名与 Tauri 一致：`(e: { payload: T }) => void`
 * - preload.ts 内部把 main 推过来的 `payload` 包回 `{ payload }`，下游零改动
 * - main.ts（统一栈）订阅 backend NDJSON 流并通过 webContents.send 转发
 * - 测试通过 `vi.mock('@/lib/tauriEvent')` 桩化，与底层 transport 解耦
 *
 * 修改此文件时请同时检查 src/lib/api.ts、src/features/send-message/__tests__/useChat.test.ts
 * 与 stream.test.ts 的 mock 字符串。
 */
import type { ElectronAPI, UnlistenFn } from '../types/electron-api';

export type { UnlistenFn };

export async function listen<T>(
  event: string,
  handler: (e: { payload: T }) => void,
): Promise<UnlistenFn> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  // Unwrap electronAPI's (payload) → wrap back to Tauri-compatible ({ payload })
  return api.listen<T>(event, (payload) => handler({ payload }));
}
