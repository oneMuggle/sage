/**
 * Tailwind 背景 token 守卫 —— 禁止 `bg-bg-<invalid>` 类名混入源码。
 *
 * 背景（2026-11-18）：使用统计「用量趋势」hover 详情卡用了 `bg-bg-elevated`，
 * 但 tailwind.config.js 的 `colors.bg` 只有 DEFAULT / muted / subtle / hover /
 * active 五个子键，`elevated` 挂在 `colors.surface` 下。Tailwind 对不存在的
 * token 不产出任何 CSS，详情卡因此背景透明（#2685 引入，仅边框和阴影可见）。
 * 同类笔误在代码库里有 18 处，全部表现为「背景静默透明」。
 *
 * 断言：src 下所有生产源码（跳过测试）中出现 `bg-bg-<x>` 时，x 必须属于
 * tailwind.config.js `colors.bg` 的合法子键集合。新增 bg 子键时需同步
 * 更新下面的 VALID_BG_SUBKEYS。
 *
 * 注意：本守卫只覆盖 `bg-bg-*` 前缀族。`text-text-tertiary`、
 * `bg-surface-hover` 等其他嵌套 token 笔误（扫描到约 55 个文件）暂不在
 * 范围内，属于后续独立清理。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'src');

/** tailwind.config.js `colors.bg` 的合法子键。 */
const VALID_BG_SUBKEYS = new Set(['muted', 'subtle', 'hover', 'active']);

/** `bg-bg-<x>`，含 `hover:` / `dark:` 等变体前缀（`\b` 在 `:` 后成立）。 */
const BG_BG_CLASS = /\bbg-bg-([a-z][a-z0-9-]*)\b/g;

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

describe('Tailwind bg token 守卫', () => {
  it('bg-bg-<x> 的 x 必须是 colors.bg 的合法子键', () => {
    const violations: Violation[] = [];
    for (const path of collectSourceFiles(SRC_DIR)) {
      const source = readFileSync(path, 'utf8');
      BG_BG_CLASS.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = BG_BG_CLASS.exec(source)) !== null) {
        if (VALID_BG_SUBKEYS.has(match[1])) continue;
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
