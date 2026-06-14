/**
 * Sage API 模块 — re-export shim (B1 过渡期)
 *
 * 实际实现已迁到 src/shared/api/。本文件保留 re-export 以让旧 caller
 * (`from '@/lib/api'`) 不破。codemod 阶段会批量改 caller,所有 caller
 * 切完后,本文件删 (B21 步骤)。
 *
 * 删除截止:v0.3.0 (B1 完成后,见 docs/plans/2026-06-13_full-quality-optimization-v2.md § 5.6)
 */
export * from '../shared/api/api';
