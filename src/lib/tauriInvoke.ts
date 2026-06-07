/**
 * Tauri `invoke()` 适配 shim。
 *
 * 双轨分支策略：
 *   - main (Tauri 2)：    export from '@tauri-apps/api/core'
 *   - release/win7 (Tauri 1.6)：export from '@tauri-apps/api/tauri'
 *
 * 两个分支都通过 src/lib/tauriInvoke.ts 间接引用 invoke，
 * 让 src/ 其余文件不需要在分支间改动 import 路径。
 *
 * 修改此文件时请同时检查 src/lib/api.ts、src/lib/store.ts、
 * src/shared/api-client/wiki.ts、src/widgets/evolution/*.tsx、
 * src/features/send-message/__tests__/useChat.test.ts 的 mock 字符串。
 */
export { invoke } from '@tauri-apps/api';
