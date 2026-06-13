/**
 * @deprecated Use `@/lib/desktopInvoke` instead. This file will be removed after 2026-12-31.
 *
 * 改名理由（2026-06-13）：
 * - 旧名 tauriInvoke 误导，让人以为对接 Tauri
 * - 实际内部委托 `window.electronAPI.invoke`（Electron）
 * - 新名 desktopInvoke 准确表达"桌面端 invoke"，与 transport 解耦
 *
 * 6 个月过渡期（2026-06 ~ 2026-12）：
 * - 旧 import 仍工作（通过本文件 re-export）
 * - 新代码禁止 import 旧名（ESLint `no-restricted-imports` 规则见 Plan C Task 11）
 * - 6 个月后（2026-12-31）删除本文件
 */
/** @deprecated use @/lib/desktopInvoke */
export { invoke } from './desktopInvoke';
