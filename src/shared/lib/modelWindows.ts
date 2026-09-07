/**
 * 模型上下文窗口映射 (U17, docs/plans/2026-09-07_coding-agent-parity-round4.md)。
 *
 * 与 backend/services/usage_tracker.py 的 PRICING_PER_MILLION_TOKENS 同构:
 * 最长前缀匹配 (小写), 未知模型回退默认窗口。数据来自各厂商 2026 公开
 * 规格文档,仅用于 UI 指示与历史预算推导,非硬约束。
 */

export const DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000;

/** [模型名前缀(小写), 上下文窗口 tokens] — 匹配时按前缀长度降序 */
const CONTEXT_WINDOWS: ReadonlyArray<readonly [string, number]> = [
  // Anthropic
  ['claude-opus', 200_000],
  ['claude-sonnet', 200_000],
  ['claude-haiku', 200_000],
  ['claude-3', 200_000],
  // Google
  ['gemini-2.5-pro', 1_048_576],
  ['gemini-2.5-flash', 1_048_576],
  ['gemini-2.0-flash', 1_048_576],
  ['gemini-1.5-pro', 2_097_152],
  ['gemini-1.5-flash', 1_048_576],
  // OpenAI
  ['o3', 200_000],
  ['o1', 200_000],
  ['gpt-4.1', 1_047_576],
  ['gpt-4o', 128_000],
  ['gpt-4-turbo', 128_000],
  ['gpt-4', 8_192],
  ['gpt-3.5', 16_385],
  // DeepSeek
  ['deepseek-reasoner', 128_000],
  ['deepseek-chat', 128_000],
];

/** 返回模型上下文窗口 (tokens);未知模型 → DEFAULT_CONTEXT_WINDOW_TOKENS。 */
export function contextWindowFor(modelId: string | null | undefined): number {
  if (!modelId) return DEFAULT_CONTEXT_WINDOW_TOKENS;
  const normalized = String(modelId).trim().toLowerCase();
  let best: readonly [string, number] | null = null;
  for (const entry of CONTEXT_WINDOWS) {
    if (
      normalized.startsWith(entry[0]) &&
      (best === null || entry[0].length > best[0].length)
    ) {
      best = entry;
    }
  }
  return best ? best[1] : DEFAULT_CONTEXT_WINDOW_TOKENS;
}

/**
 * L9-lite 历史预算推导: 窗口的 75%,预留 25% 给 system/工具 schema/回复。
 * 用户在设置里显式配置的 maxContext (≥20000) 优先——与后端 ``data.max_context``
 * 的有效性阈值一致,避免小配置值被窗口推导覆盖后反而放大预算。
 */
export function historyBudgetFor(
  modelId: string | null | undefined,
  userMaxContext?: number | null,
): number {
  if (userMaxContext != null && userMaxContext >= 20_000) return userMaxContext;
  return Math.floor(contextWindowFor(modelId) * 0.75);
}
