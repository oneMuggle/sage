/**
 * 模型上下文窗口 — catalog resolution (Task 5, 2026-09-15).
 *
 * 移除旧硬编码前缀映射 (CONTEXT_WINDOWS), 改为由后端 model catalog
 * 解析后传入 effective window. 前端不再本地猜测模型窗口大小.
 *
 * 回退默认: 当 catalog 无数据且无显式 fixed 值时使用 4096 (与后端
 * effective_window 的 _UNKNOWN_AUTOMATIC_WINDOW 一致).
 */

export const DEFAULT_CONTEXT_WINDOW_TOKENS = 4096;

/**
 * 返回有效上下文窗口. 优先使用 catalog 解析值, 否则回退到默认.
 *
 * @param catalogWindow - 后端 catalog 解析的有效窗口; null/undefined 表示未知
 * @param fixedWindow - 用户在设置中手动配置的 maxContext; 仅 auto=false 时使用
 * @param autoContext - 是否自动推断 (true = 忽略 fixedWindow)
 */
export function resolvedContextWindow(
  catalogWindow: number | null | undefined,
  fixedWindow?: number | null,
  autoContext: boolean = true,
): number {
  if (autoContext) {
    return catalogWindow ?? DEFAULT_CONTEXT_WINDOW_TOKENS;
  }
  // Manual: use fixed, but cap by catalog if known
  const fixed = fixedWindow ?? DEFAULT_CONTEXT_WINDOW_TOKENS;
  if (catalogWindow != null && catalogWindow > 0) {
    return Math.min(fixed, catalogWindow);
  }
  return fixed;
}

/**
 * 历史 token 预算: 有效窗口减去预留 (system/tools/output), 下限 0.
 *
 * 不再使用旧 >=20000 门槛或固定 75% 系数. 预留由后端根据实际
 * system prompt / tool schema 大小计算后传入.
 *
 * @param effectiveWindow - resolvedContextWindow 返回的值
 * @param reserve - system/tool/output 预留 tokens (默认 16384)
 */
export function historyBudgetFor(
  effectiveWindow: number,
  reserve: number = 16384,
): number {
  return Math.max(0, Math.floor(effectiveWindow - reserve));
}

/**
 * @deprecated 使用 resolvedContextWindow 替代. 保留仅为兼容过渡,
 * 始终返回 DEFAULT_CONTEXT_WINDOW_TOKENS.
 */
export function contextWindowFor(_modelId: string | null | undefined): number {
  return DEFAULT_CONTEXT_WINDOW_TOKENS;
}
