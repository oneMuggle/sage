/**
 * Renderer-side IPC shim — invoke(cmd, args) → Electron main process → backend HTTP.
 *
 * 历史背景（2026-06-13 Phase 2 之前）：re-export of `@tauri-apps/api/core` invoke，
 * 直接对接 Tauri 2.1.1 主进程。Phase 0 决定换栈（Tauri/Wry hard-depends on WebView2，
 * Win10+），Phase 1 引入 Electron 21.4.4，Phase 2 把 shim 内部切到 electronAPI。
 *
 * 现状（2026-06-13 Phase 2）：
 * - shim 仍暴露同名 `invoke<T>(cmd, args)` 签名，下游调用方（src/lib/api.ts 等）零改动
 * - 内部委托给 `window.electronAPI.invoke`（preload.ts 通过 contextBridge 注入）
 * - 主进程（electron/main.ts）再把 invoke 转成对 backend FastAPI 的 HTTP 调用
 * - 测试通过 `vi.mock('@/lib/tauriInvoke')` 桩化，与底层 transport（Tauri/Electron）解耦
 *
 * 修改此文件时请同时检查 src/lib/api.ts、src/lib/store.ts、
 * src/shared/api-client/wiki.ts、src/widgets/evolution/*.tsx、
 * src/features/send-message/__tests__/useChat.test.ts 与 stream.test.ts 的 mock 字符串。
 */
import type { ElectronAPI } from '../types/electron-api';

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