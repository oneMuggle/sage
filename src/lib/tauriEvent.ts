/**
 * Tauri `listen()` 适配 shim (PR-6 chat streaming)
 *
 * 现状（2026-06）：main 与 release/win7 都使用 Tauri 2.1.1
 * (release/win7 走 Win7 CVE backport fork，详见 docs/technical/20-win7-tauri-compat.md)，
 * 两边 `@tauri-apps/api/event` 路径一致。
 *
 * 保留 shim 是为了与 tauriInvoke.ts 的模式统一，未来若路径漂移可以集中调整；
 * 同时方便测试 `vi.mock('@/lib/tauriEvent')` 直接桩化 listen。
 *
 * 修改此文件时请同时检查 src/lib/api.ts 和
 * src/features/send-message/__tests__/stream.test.ts 的 mock 字符串。
 */
export { listen, type UnlistenFn } from '@tauri-apps/api/event';
