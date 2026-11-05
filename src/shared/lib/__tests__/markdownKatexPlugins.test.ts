/**
 * 仓库级不变量：凡是用 rehype-katex 的文件，必须同时用 remark-math。
 *
 * 根因背景（alpha.36 Bug #6，2026-10 在 main 上复发）：
 *   rehype-katex 只负责把 **已有的 math AST** 渲染成 KaTeX 节点；
 *   没有 remark-math 时 remark 根本不产出 math AST，
 *   于是 `$E=mc^2$` 原样保留为纯文本，而插件配置看上去「已经挂了 KaTeX」。
 *
 * 这个组合错误很难靠肉眼发现（代码里有 rehypeKatex，看起来是对的），
 * 而且曾经在 3 个文件里同时出现。所以除了单组件行为测试，还在这里锁
 * 插件配对不变量 + 锁住消费方走共享管线。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

// __tests__ -> lib -> shared -> src
const SRC_ROOT = join(__dirname, '..', '..', '..');

const SCAN_EXTENSIONS = ['.ts', '.tsx'];
const SKIP_DIRS = new Set(['__tests__', 'node_modules', 'dist']);

function collectSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (SKIP_DIRS.has(entry)) continue;
      collectSourceFiles(full, out);
      continue;
    }
    if (SCAN_EXTENSIONS.some((ext) => entry.endsWith(ext))) out.push(full);
  }
  return out;
}

const read = (relativePath: string) => readFileSync(join(SRC_ROOT, relativePath), 'utf8');

describe('Markdown KaTeX 插件一致性', () => {
  it('任何 import 了 rehype-katex 的源文件也必须 import remark-math', () => {
    const offenders: string[] = [];
    for (const file of collectSourceFiles(SRC_ROOT)) {
      const source = readFileSync(file, 'utf8');
      const usesKatex = /from\s+['"]rehype-katex['"]/.test(source);
      if (!usesKatex) continue;
      const usesMath = /from\s+['"]remark-math['"]/.test(source);
      if (!usesMath) offenders.push(relative(SRC_ROOT, file).replace(/\\/g, '/'));
    }
    expect(
      offenders,
      `以下文件挂了 rehype-katex 却缺 remark-math，$math$ 会降级为纯文本：\n` +
        offenders.map((f) => `  - ${f}`).join('\n'),
    ).toEqual([]);
  });

  it('共享管线 plugins.ts 同时导出 remark-math 与 rehype-katex', () => {
    const source = read('widgets/markdown/plugins.ts');
    expect(source).toMatch(/from\s+['"]remark-math['"]/);
    expect(source).toMatch(/from\s+['"]rehype-katex['"]/);
    expect(source).toMatch(/export const MD_REMARK_PLUGINS[\s\S]*?remarkMath/);
    expect(source).toMatch(/export const MD_REHYPE_PLUGINS[\s\S]*?rehypeKatex/);
  });

  it('BtwOverlay / HelpTab 走共享管线（曾各自只挂 remarkGfm + rehypeKatex）', () => {
    for (const file of ['features/chat/BtwOverlay.tsx', 'pages/Help/HelpTab.tsx']) {
      const source = read(file);
      expect(source, `${file} 应导入共享插件集合`).toMatch(
        /import\s*\{[^}]*MD_REMARK_PLUGINS[^}]*\}\s*from\s*['"][^'"]*markdown\/plugins['"]/,
      );
      expect(source, `${file} 应使用 MD_REMARK_PLUGINS`).toMatch(
        /remarkPlugins=\{MD_REMARK_PLUGINS\}/,
      );
    }
  });

  it('wiki MarkdownPreview 委托给共享 <Markdown> 渲染器', () => {
    const source = read('widgets/wiki/MarkdownPreview.tsx');
    expect(source).toMatch(/from\s+['"]\.\.\/markdown['"]/);
    expect(source).toMatch(/<Markdown\b/);
  });
});
