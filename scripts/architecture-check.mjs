#!/usr/bin/env node

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname } from 'path';

const policy = JSON.parse(readFileSync('architecture-policy.json', 'utf-8'));
const maxFileLines = policy.global.maxFileLines;

function countLines(filePath) {
  return readFileSync(filePath, 'utf-8').split('\n').length;
}

function walkDir(dir, fileList = []) {
  const files = readdirSync(dir);
  for (const file of files) {
    const filePath = join(dir, file);
    if (statSync(filePath).isDirectory()) {
      if (!filePath.includes('node_modules') && !filePath.includes('.git')) {
        walkDir(filePath, fileList);
      }
    } else if (extname(filePath) === '.ts' || extname(filePath) === '.tsx' || extname(filePath) === '.py') {
      fileList.push(filePath);
    }
  }
  return fileList;
}

function checkMaxFileLines() {
  const violations = [];
  const files = walkDir('.');
  for (const file of files) {
    const lines = countLines(file);
    if (lines > maxFileLines) {
      violations.push({ file, lines, over: lines - maxFileLines });
    }
  }
  return violations;
}

const violations = checkMaxFileLines();
if (violations.length > 0) {
  console.error(`Found ${violations.length} files exceeding ${maxFileLines} lines:`);
  for (const v of violations) {
    console.error(`  ${v.file}: ${v.lines} lines (+${v.over})`);
  }
  process.exit(1);
} else {
  console.log(`All files within ${maxFileLines} lines limit.`);
}
