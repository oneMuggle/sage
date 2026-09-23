#!/usr/bin/env node
// 仓库根目录过程产物安全清理（2026-09-22 housekeeping）。
//
// 设计约束（防误删，参考 ZCode scripts/clean.mjs 的思路）：
// - 只清理 ALLOWLIST 明确列出的根目录条目——新增可清理项必须改这个文件，
//   脚本永远不会"顺手"删除清单之外的东西；
// - 只扫仓库根一层，不递归——源码目录天然不可达；
// - 默认 dry-run（只列出将要删除的条目与体积），加 `--yes` 才真正删除。
//
// 用法：
//   node scripts/clean.mjs            # 预览
//   node scripts/clean.mjs --yes      # 执行删除
import { readdirSync, rmSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = resolve(fileURLToPath(import.meta.url), '..', '..');

/** 允许删除的根目录文件（相对根的精确名或正则）。 */
const FILE_PATTERNS = [
  /^nul$/, // Windows `> nul` 重定向误产物（0 字节）
  /^recent\.json$/, // 会话级状态缓存
  /^\.arena_q\.tmp$/,
  /^_push\.log$/,
  /^\.final-cleanup\.ps1$/,
  /^\.final_audit\.log$/,
  /^r\d+-msg\.txt$/, // 轮次 PR/commit message 草稿（内容已随对应 PR 落库）
  /^\.r\d+[a-z0-9-]*-plan-draft\.md$/,
  /^\.r\d+[a-z0-9-]*-pr-body\.md$/,
  /^\.p\d+[a-z0-9]*\.log$/, // .p1081*.log / .p5a*.log 等轮次过程日志
  /^\.tmp-[a-z0-9-]+\.log$/, // .tmp-p5-lint.log 等会话临时日志
  /^\.r\d+[a-z0-9-]*\.log$/, // .r2-align-step1.log / .r3w1.log 等
  /^\.fc\.log$/,
];

/** 允许删除的根目录（递归）。仅限会话级临时目录。 */
const DIR_PATTERNS = [
  /^\.tmp-arena-[a-z0-9-]+$/, // S0/P1..P5 冒烟工作副本
  /^\.tmp-auth-device$/,
  /^\.tmp-audit$/,
];

const yes = process.argv.includes('--yes');

const entries = readdirSync(REPO_ROOT);
const hits = [];
for (const name of entries) {
  const full = join(REPO_ROOT, name);
  let stat;
  try {
    stat = statSync(full);
  } catch {
    continue; // 竞态：条目刚好消失
  }
  const isFile = stat.isFile();
  const patterns = isFile ? FILE_PATTERNS : DIR_PATTERNS;
  if (patterns.some((re) => re.test(name))) {
    hits.push({ name, size: stat.size, isFile });
  }
}

if (hits.length === 0) {
  console.log('根目录没有可清理的过程产物。');
  process.exit(0);
}

let totalBytes = 0;
for (const { name, size, isFile } of hits) {
  totalBytes += size;
  console.log(`${yes ? '删除' : '将删除'} ${isFile ? 'file' : 'dir '} ${name} (${formatBytes(size)})`);
}
console.log(`共 ${hits.length} 项，${formatBytes(totalBytes)}`);

if (!yes) {
  console.log('\ndry-run 预览（未删除任何内容）。确认无误后执行：node scripts/clean.mjs --yes');
  process.exit(0);
}

for (const { name, isFile } of hits) {
  rmSync(join(REPO_ROOT, name), { recursive: !isFile, force: true });
}
console.log(`\n已删除 ${hits.length} 项。`);

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
