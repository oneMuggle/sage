#!/usr/bin/env node
// 分支新鲜度门禁（ZCode check-workspace-freshness 思路的 sage 版）。
//
// 背景：并行会话高频落库，若开工的 base 落后 upstream 太多，合并时会
// 带入他人改动（实例：#1381 因基线被外部基线更新而变红）。本脚本在
// 开工/推送前给出客观的落后度量，超阈值即失败。
//
// 用法：
//   node scripts/check-branch-freshness.mjs                     # 检查当前分支 vs origin/main
//   node scripts/check-branch-freshness.mjs --base release/win7  # 指定 upstream
//   node scripts/check-branch-freshness.mjs --threshold 20      # 覆盖阈值（默认 50）
//
// 退出码：0 = 新鲜或落后不超阈值；1 = 落后超阈值或无法比较。
// 需要 git 在 PATH 中；fetch 由调用方决定是否先做（脚本只读本地引用，
// 避免在网络受限环境下卡死——需要最新数据请先 `git fetch origin`）。
import { execSync } from 'node:child_process';

const args = process.argv.slice(2);
function argOf(flag, fallback) {
  const i = args.indexOf(flag);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
}
const base = argOf('--base', 'origin/main');
const threshold = Number(argOf('--threshold', '50'));

function revCount(range) {
  try {
    return Number(execSync(`git rev-list --count ${range}`, { encoding: 'utf8' }).trim());
  } catch {
    return NaN;
  }
}

const branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8' }).trim();
const ahead = revCount(`${base}..HEAD`);
const behind = revCount(`HEAD..${base}`);

if (Number.isNaN(ahead) || Number.isNaN(behind)) {
  console.error(`无法比较 ${branch} 与 ${base}（引用缺失？先 git fetch origin）`);
  process.exit(1);
}

console.log(`分支 ${branch}：ahead ${ahead} / behind ${behind}（阈值 ${threshold}）`);

if (behind > threshold) {
  console.error(
    `::error::落后 ${base} ${behind} 个提交（> ${threshold}）。` +
      '先 `git merge --ff-only ' + base + '` 或 rebase 再继续，避免把旧基线上的工作带进合并。',
  );
  process.exit(1);
}
console.log('新鲜度检查通过。');
