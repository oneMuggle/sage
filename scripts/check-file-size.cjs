#!/usr/bin/env node
/**
 * File size guardrail — 扫描源文件，告警超过 800 行的文件。
 *
 * 2026-09-22 (ZCode-inspired optimization): 参考 ZCode 的 architecture policy，
 * 防止单文件规模膨胀。ZCode 限制 500 行，Sage 放宽到 800 行以匹配当前代码库现状。
 *
 * 用法:
 *   node scripts/check-file-size.js [maxLines]
 *   node scripts/check-file-size.js        # 默认 800 行
 *   node scripts/check-file-size.js 500    # 自定义阈值
 *
 * 退出码:
 *   0 — 无违规文件
 *   1 — 存在超过阈值的文件
 */

const fs = require('fs');
const path = require('path');

const MAX_LINES = parseInt(process.argv[2] || '800', 10);

// 扫描目录（排除 node_modules、dist、.worktrees 等）
const SCAN_DIRS = ['src', 'electron', 'backend'];
const EXCLUDE_PATTERNS = [
  /node_modules/,
  /dist(-electron)?/,
  /\.worktrees/,
  /\.claude/,
  /__pycache__/,
  /\.git/,
  /archive/,
  /\.test\.(ts|tsx|js|jsx|py)$/,
  /\.spec\.(ts|tsx|js|jsx|py)$/,
];

const EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.py'];

function countLines(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  return content.split('\n').length;
}

function shouldExclude(filePath, projectRoot) {
  // 只检查相对于 projectRoot 的路径，避免父目录路径（如 .worktrees/）误触发排除
  const relPath = path.relative(projectRoot, filePath);
  return EXCLUDE_PATTERNS.some((pattern) => pattern.test(relPath));
}

function walkDir(dir, projectRoot) {
  const results = [];
  if (!fs.existsSync(dir)) return results;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (shouldExclude(fullPath, projectRoot)) continue;

    if (entry.isDirectory()) {
      results.push(...walkDir(fullPath, projectRoot));
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name);
      if (EXTENSIONS.includes(ext)) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

function main() {
  const projectRoot = path.dirname(path.dirname(__filename));
  const violations = [];

  for (const scanDir of SCAN_DIRS) {
    const fullDir = path.join(projectRoot, scanDir);
    const files = walkDir(fullDir, projectRoot);

    for (const file of files) {
      const lines = countLines(file);
      if (lines > MAX_LINES) {
        violations.push({ file: path.relative(projectRoot, file), lines });
      }
    }
  }

  // 按行数降序排列
  violations.sort((a, b) => b.lines - a.lines);

  if (violations.length === 0) {
    console.log(`✅ 无文件超过 ${MAX_LINES} 行`);
    process.exit(0);
  }

  console.error(`❌ 发现 ${violations.length} 个文件超过 ${MAX_LINES} 行:`);
  for (const { file, lines } of violations) {
    console.error(`  ${lines} 行: ${file}`);
  }
  console.error(`\n建议: 拆分大文件，提取子模块或工具函数`);
  process.exit(1);
}

main();
