#!/usr/bin/env node
// 渲染产物体积门禁（ZCode audit-bundle-size 思路的 sage 版）。
//
// 背景：#1401 把 dist/assets 从 18MB/450 chunk 砍到 10MB/178（shiki 全量
// bundle → 细粒度），#1419 把 index 主 chunk 从 1528KB 砍到 1140KB
// （CodeMirror lazy）。没有门禁时这类回潮无法察觉——shiki 换回全量
// bundle 或大依赖被静态引入都会静默膨胀安装包。
//
// 预算（2026-09-24 实测留 ~10% 余量，超限即失败）：
//   - dist/assets 总体积   ≤ 12MB   （实测 ~9.9MB）
//   - 最大单个 .js chunk   ≤ 1.6MB  （实测 index 主 chunk ~1.45MB）
//
// 用法：npm run build 之后执行 `node scripts/check-bundle-size.mjs`。
// 退出码：0 = 全部预算内；1 = 超限或 dist 不存在。
// 若为有意的功能增长导致超限，更新本文件 BUDGETS 并在 PR 说明依据
// （棘轮协议：只上调，不下调）。
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ASSETS = 'dist/assets';

const BUDGETS = [
  { name: 'dist/assets 总体积', max: 12 * 1024 * 1024 },
  { name: '最大单个 .js chunk', max: 1.6 * 1024 * 1024, filter: (f) => f.endsWith('.js') },
];

if (!readdirSync('.').includes('dist')) {
  console.error('dist/ 不存在——先 `npm run build` 再跑门禁。');
  process.exit(1);
}

const files = [];
(function walk(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else files.push({ path: p, size: st.size });
  }
})(ASSETS);

const totalSize = files.reduce((sum, f) => sum + f.size, 0);
const largestJs = files
  .filter((f) => f.path.endsWith('.js'))
  .sort((a, b) => b.size - a.size)[0];

function fmt(n) {
  return `${(n / 1024 / 1024).toFixed(2)}MB (${(n / 1024).toFixed(0)}KB)`;
}

let failed = false;
for (const budget of BUDGETS) {
  const value = budget.filter
    ? largestJs
      ? largestJs.size
      : 0
    : totalSize;
  const ok = value <= budget.max;
  if (!ok) failed = true;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${budget.name}: ${fmt(value)} / 预算 ${fmt(budget.max)}`);
}
console.log(`dist/assets: ${files.length} 个文件，共 ${fmt(totalSize)}`);
if (largestJs) console.log(`最大 .js: ${largestJs.path} ${fmt(largestJs.size)}`);

process.exit(failed ? 1 : 0);
