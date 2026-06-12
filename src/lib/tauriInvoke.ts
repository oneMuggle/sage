/**
 * Tauri `invoke()` 适配 shim。
 *
 * 历史背景：早期 release/win7 走 Tauri 1.6 路线 (`@tauri-apps/api/tauri`)，
 * main 走 Tauri 2.x (`@tauri-apps/api/core`)，shim 让 src/ 其余文件统一引用。
 *
 * 现状（2026-06）：release/win7 已切换到 **Tauri 2.1.1 + Win7 CVE backport fork**
 * (详见 docs/technical/20-win7-tauri-compat.md)，与 main 共用 Tauri 2.x npm 包。
 * 两分支的 invoke 路径现在一致 (`@tauri-apps/api/core`)。
 *
 * 保留 shim 的目的：
 *   1) 兜底未来 Tauri 版本路径漂移；
 *   2) 测试通过 `vi.mock('@/lib/tauriInvoke')` 即可桩化 invoke，不必关心 Tauri 内部布局。
 *
 * 修改此文件时请同时检查 src/lib/api.ts、src/lib/store.ts、
 * src/shared/api-client/wiki.ts、src/widgets/evolution/*.tsx、
 * src/features/send-message/__tests__/useChat.test.ts 的 mock 字符串。
 */
export { invoke } from '@tauri-apps/api/core';
