/**
 * desktopInvoke.ts — re-export shim (B1 过渡期, unit 3)
 *
 * 实际实现已迁到 src/shared/api/desktopInvoke.ts。本文件保留 re-export 以让
 * 旧 caller 不破。codemod 阶段批量改 caller,所有 caller 切完后,
 * 本文件删 (B21)。
 *
 * 删除截止:v0.3.0 (B1 完成后)
 */
export * from '../shared/api/desktopInvoke';
