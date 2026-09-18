/**
 * 上下文窗口档位预设与 token 输入换算 helpers
 * (2026-09-18 端点限额 + 上下文输入优化 P0-A, 见
 * docs/superpowers/specs/2026-09-18-endpoint-quota-model-settings-optimization-design.md §4)
 *
 * 档位 token 数按厂商惯用值而非统一进制: 128K=131072 (OpenAI), 200K=200000
 * (Anthropic), 1M=1000000 (Gemini)。自定义单位乘数固定十进制 (K=1e3, M=1e6),
 * 用户输入 512K 即 512000。
 */

export const CONTEXT_MIN_TOKENS = 1024;
export const CONTEXT_MAX_TOKENS = 10_000_000;

export interface ContextPreset {
  label: string;
  tokens: number;
}

export const CONTEXT_PRESETS: readonly ContextPreset[] = [
  { label: '4K', tokens: 4096 },
  { label: '8K', tokens: 8192 },
  { label: '16K', tokens: 16384 },
  { label: '32K', tokens: 32768 },
  { label: '64K', tokens: 65536 },
  { label: '128K', tokens: 131072 },
  { label: '200K', tokens: 200000 },
  { label: '256K', tokens: 262144 },
  { label: '512K', tokens: 524288 },
  { label: '1M', tokens: 1000000 },
  { label: '2M', tokens: 2000000 },
];

export type TokenUnit = 'tokens' | 'K' | 'M';

export const TOKEN_UNITS: readonly { value: TokenUnit; label: string }[] = [
  { value: 'tokens', label: 'tokens' },
  { value: 'K', label: 'K' },
  { value: 'M', label: 'M' },
];

export const TOKEN_UNIT_MULTIPLIERS: Record<TokenUnit, number> = {
  tokens: 1,
  K: 1_000,
  M: 1_000_000,
};

/** 把 token 数钳制到 [CONTEXT_MIN_TOKENS, CONTEXT_MAX_TOKENS]。 */
export function clampTokenCount(n: number): number {
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(Math.max(Math.round(n), CONTEXT_MIN_TOKENS), CONTEXT_MAX_TOKENS);
}

/** 自定义输入 (数值 + 单位) → 归一化 token 数; 非法输入返回 0。 */
export function parseTokenInput(text: string, unit: TokenUnit): number {
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return clampTokenCount(value * TOKEN_UNIT_MULTIPLIERS[unit]);
}

/** 归一化 token 数 → 友好的自定义输入初值 (数值文本 + 单位)。 */
export function deriveTokenInput(tokens: number): { text: string; unit: TokenUnit } {
  if (tokens >= 1_000_000 && tokens % 100_000 === 0) {
    return { text: String(tokens / 1_000_000), unit: 'M' };
  }
  if (tokens >= 1_000 && tokens % 100 === 0) {
    return { text: String(tokens / 1_000), unit: 'K' };
  }
  return { text: String(tokens), unit: 'tokens' };
}

/** token 数 → 展示文本: 命中预设用档位标签, 整千/整百千用 K/M, 否则原样。 */
export function formatTokens(tokens: number): string {
  const preset = CONTEXT_PRESETS.find((p) => p.tokens === tokens);
  if (preset) return preset.label;
  if (tokens >= 1_000_000 && tokens % 1_000_000 === 0) return `${tokens / 1_000_000}M`;
  if (tokens >= 1_000 && tokens % 1_000 === 0) return `${tokens / 1_000}K`;
  return String(tokens);
}
