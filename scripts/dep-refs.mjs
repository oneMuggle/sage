#!/usr/bin/env node

import { readFileSync } from 'fs';
import { extname } from 'path';

function analyzePython(filePath) {
  // 使用 Python ast 模块分析（这里简化为 grep）
  const content = readFileSync(filePath, 'utf-8');
  const imports = content.match(/^from\s+(\S+)\s+import/gm) || [];
  return imports;
}

function analyzeTypeScript(filePath) {
  // 使用 TypeScript Compiler API（这里简化为 grep）
  const content = readFileSync(filePath, 'utf-8');
  const imports = content.match(/^import.*from\s+['"]([^'"]+)['"]/gm) || [];
  return imports;
}

const filePath = process.argv[2];
if (!filePath) {
  console.error('Usage: node scripts/dep-refs.mjs <file>');
  process.exit(1);
}

const ext = extname(filePath);
const imports = ext === '.py' ? analyzePython(filePath) : analyzeTypeScript(filePath);

console.log(`Dependencies of ${filePath}:`);
for (const imp of imports) {
  console.log(`  ${imp}`);
}
