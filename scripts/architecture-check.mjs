#!/usr/bin/env node

import { readFileSync, readdirSync, statSync, existsSync } from 'fs';
import { join, extname, sep } from 'path';

const policy = JSON.parse(readFileSync('architecture-policy.json', 'utf-8'));
const maxFileLines = policy.global.maxFileLines;

// Baseline keys always use POSIX separators (repo-standard); on Windows
// join() yields backslash paths, so normalize before any baseline lookup —
// otherwise every file looks "not in baseline" and the ratchet silently
// stops working on Windows dev machines.
function toPosix(p) {
  return p.split(sep).join('/');
}

// Load baseline if it exists. The baseline maps file paths to their
// baselined line counts. Files in the baseline are only flagged if they
// have GROWN beyond their baselined count (ratchet). Files NOT in the
// baseline are flagged if they exceed maxFileLines (new violations).
const BASELINE_PATH = 'architecture-baseline.json';
let baseline = {};
if (existsSync(BASELINE_PATH)) {
  const baselineData = JSON.parse(readFileSync(BASELINE_PATH, 'utf-8'));
  baseline = baselineData.files || {};
}

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
  const newViolations = [];
  const growthViolations = [];
  const files = walkDir('.');
  for (const file of files) {
    const lines = countLines(file);
    const baselinedCount = baseline[toPosix(file)];

    if (baselinedCount !== undefined) {
      // File is in baseline: only flag if it has GROWN
      if (lines > baselinedCount) {
        growthViolations.push({
          file,
          lines,
          baselined: baselinedCount,
          over: lines - baselinedCount,
        });
      }
    } else {
      // File is NOT in baseline: flag if it exceeds maxFileLines
      if (lines > maxFileLines) {
        newViolations.push({
          file,
          lines,
          over: lines - maxFileLines,
        });
      }
    }
  }
  return { newViolations, growthViolations };
}

const { newViolations, growthViolations } = checkMaxFileLines();
const totalViolations = newViolations.length + growthViolations.length;

// --json mode: emit machine-readable violations (used by the CI
// ratchet-hint step to post a ready-to-paste baseline bump comment).
// Exit code is still 0 in --json mode so the hint step can decide
// for itself; the normal run below keeps the enforcing exit code.
if (process.argv.includes('--json')) {
  process.stdout.write(
    JSON.stringify({ newViolations, growthViolations }, null, 2) + '\n',
  );
  process.exit(0);
}

if (totalViolations > 0) {
  if (newViolations.length > 0) {
    console.error(`${newViolations.length} NEW files exceeding ${maxFileLines} lines:`);
    for (const v of newViolations) {
      console.error(`  ${v.file}: ${v.lines} lines (+${v.over})`);
    }
    console.error(
      `Fix: refactor the file(s) below ${maxFileLines} lines. ` +
        `If a file is pre-existing legacy that cannot be split in this PR, ` +
        `add it to architecture-baseline.json with its current line count.`,
    );
  }
  if (growthViolations.length > 0) {
    console.error(`${growthViolations.length} BASELINED files that have grown:`);
    for (const v of growthViolations) {
      console.error(`  ${v.file}: ${v.lines} lines (baseline: ${v.baselined}, +${v.over})`);
    }
    console.error(
      `Fix: if the growth is intentional, update the file's entry in ` +
        `architecture-baseline.json to ${growthViolations.map((v) => v.lines).join(' / ')} ` +
        `(ratchet protocol — do not lower existing entries). ` +
        `Otherwise, shrink the file back to its baselined size.`,
    );
  }
  process.exit(1);
} else {
  const baselinedCount = Object.keys(baseline).length;
  if (baselinedCount > 0) {
    console.log(`All files within limits (${baselinedCount} baselined, ${maxFileLines}-line max for new files).`);
  } else {
    console.log(`All files within ${maxFileLines} lines limit.`);
  }
}
