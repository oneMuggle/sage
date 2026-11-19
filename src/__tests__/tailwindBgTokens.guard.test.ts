/**
 * Tailwind 嵌套颜色 token 守卫 —— 禁止 `bg-bg-elevated` / `text-text-tertiary`
 * 这类「引用了不存在的颜色子键」的类名混入源码。
 *
 * 背景（2026-11-18）：使用统计「用量趋势」hover 详情卡用了 `bg-bg-elevated`，
 * 但 tailwind.config.js 的 `colors.bg` 只有 DEFAULT / muted / subtle / hover /
 * active 五个子键，`elevated` 挂在 `colors.surface` 下。Tailwind 对不存在的
 * token 不产出任何 CSS —— 详情卡背景静默透明（#2685 引入，仅边框和阴影可见）。
 * 首轮修复了 18 处 `bg-bg-*`（PR #3129）。2026-11-19 全量清理时又发现
 * `text-text-tertiary` / `bg-surface-hover` / `border-line-subtle` 等同族笔误
 * 约 188 处（62 个文件），一并修正并把守卫扩展到全部嵌套颜色 token。
 *
 * 断言：src 下所有生产源码（跳过测试）中出现 `<utility>-<group>-<subkey>`
 * （utility ∈ bg/text/border/ring/fill，group ∈ bg/surface/text/border/line/ui）
 * 时，subkey 必须属于 tailwind.config.js 对应颜色组的合法子键。
 *
 * 合法例外：
 * - `text-ui-*` 是 fontSize 刻度（ui-xs/ui-sm/ui-base/ui-lg/ui-xl/ui-caption…），
 *   不是颜色，跳过；
 * - 不含子键的裸类（如 `border-line`、`ring-border`）是 DEFAULT 颜色，不受影响。
 *
 * 修改 tailwind.config.js 颜色组时需同步更新 VALID_SUBKEYS。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'src');

/** tailwind.config.js `colors` 各组的合法子键（DEFAULT 不在列，裸类不触发匹配）。 */
const VALID_SUBKEYS: Record<string, Set<string>> = {
  bg: new Set(['muted', 'subtle', 'hover', 'active']),
  surface: new Set(['elevated', 'overlay']),
  text: new Set(['secondary', 'muted', 'inverse']),
  border: new Set(['hover']),
  line: new Set(['strong']),
  ui: new Set(['page', 'panel', 'card', 'overlay', 'fg', 'subtle']),
};

/**
 * `<utility>-<group>-<subkey>`，含 `hover:` / `dark:` 等变体前缀（`\b` 在 `:` 后成立）。
 * 不含 `stroke-`（`stroke-linecap` / `stroke-linejoin` 会误伤）。
 */
const NESTED_TOKEN = /\b(?:bg|text|border|ring|fill)-(bg|surface|text|border|line|ui)-([a-z][a-z0-9-]*)\b/g;

interface Violation {
  file: string;
  line: number;
  token: string;
}

function collectSourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry !== '__tests__') collectSourceFiles(path, acc);
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry) && !/\.test\./.test(entry)) acc.push(path);
  }
  return acc;
}

function lineAt(source: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index && i < source.length; i += 1) {
    if (source[i] === '\n') line += 1;
  }
  return line;
}

function tokenStart(source: string, matchIndex: number): string {
  return source.slice(matchIndex, matchIndex + 5);
}

describe('Tailwind 嵌套颜色 token 守卫', () => {
  it('<utility>-<group>-<subkey> 的 subkey 必须是颜色组合法子键', () => {
    const violations: Violation[] = [];
    for (const path of collectSourceFiles(SRC_DIR)) {
      const source = readFileSync(path, 'utf8');
      NESTED_TOKEN.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = NESTED_TOKEN.exec(source)) !== null) {
        const group = match[1];
        const subkey = match[2];
        // text-ui-* 是 fontSize 刻度，不是颜色 token。
        if (tokenStart(source, match.index).startsWith('text-') && group === 'ui') continue;
        if (VALID_SUBKEYS[group]?.has(subkey)) continue;
        violations.push({
          file: relative(SRC_DIR, path),
          line: lineAt(source, match.index),
          token: match[0],
        });
      }
    }
    expect(violations).toEqual([]);
  });
});
