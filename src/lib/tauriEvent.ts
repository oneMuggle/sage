/**
 * Tauri `listen()` 适配 shim (PR-6 chat streaming)
 *
 * 双轨分支策略 (与 tauriInvoke.ts 一致):
 *   - main (Tauri 2):       export from '@tauri-apps/api/event'
 *   - release/win7 (Tauri 1.6): export from '@tauri-apps/api/event'
 *
 * 两个分支都从 `@tauri-apps/api/event` 导出 listen/emit,
 * 路径一致; 保留 shim 是为了与 tauriInvoke.ts 的模式统一,
 * 未来若 Tauri 1.6 升级后路径漂移可以集中调整。
 *
 * 修改此文件时请同时检查 src/lib/api.ts 和
 * src/features/send-message/__tests__/stream.test.ts 的 mock 字符串。
 */
export { listen, type UnlistenFn } from '@tauri-apps/api/event';
