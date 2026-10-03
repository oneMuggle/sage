#!/usr/bin/env node

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'fs';
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

// Directories never scanned: third-party installs, nested checkouts, caches.
// Dot-prefixed dirs (.worktrees, .venv*, .git, .qoder ...) are dev-machine
// artifacts that CI clean checkouts never contain — walking them makes LOCAL
// runs diverge from CI semantics (hundreds of phantom "violations") while the
// committed gate stays identical.
const SKIP_DIR_NAMES = new Set([
  'node_modules',
  'venv',
  'dist',
  'dist-electron',
  'coverage',
  '__pycache__',
  'export_assets',
]);

function shouldSkipDir(name) {
  return SKIP_DIR_NAMES.has(name) || name.startsWith('.');
}

function walkDir(dir, fileList = []) {
  const files = readdirSync(dir);
  for (const file of files) {
    const filePath = join(dir, file);
    if (statSync(filePath).isDirectory()) {
      if (!shouldSkipDir(file)) {
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
  // POSIX path -> current line count of every scanned file. Feeds the slack
  // report and --tighten, which both need the file's CURRENT size.
  const counts = new Map();
  const files = walkDir('.');
  for (const file of files) {
    const lines = countLines(file);
    counts.set(toPosix(file), lines);
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
  return { newViolations, growthViolations, counts };
}

const { newViolations, growthViolations, counts } = checkMaxFileLines();
const totalViolations = newViolations.length + growthViolations.length;

// -- Baseline slack ----------------------------------------------------------
// The ratchet only stops a baselined file from GROWING past its entry; it does
// not lock in shrinkage. A file baselined at 3976 that was cut to 2367 can
// silently regrow 1600 lines while CI stays green. That unclaimed headroom is
// "slack"; --tighten lowers every entry to the file's current size.
function computeSlack() {
  const entries = [];
  for (const [key, baselined] of Object.entries(baseline)) {
    const lines = counts.get(key);
    if (lines !== undefined && lines < baselined) {
      entries.push({ file: key, lines, baselined, slack: baselined - lines });
    }
  }
  entries.sort((a, b) => b.slack - a.slack);
  return { entries, total: entries.reduce((sum, e) => sum + e.slack, 0) };
}

// What --tighten does to each baseline entry. It never raises one:
//   file gone / no longer scanned -> drop  (dead entry)
//   file now <= maxFileLines      -> drop  (debt paid; the global limit applies)
//   file smaller than its entry   -> lower to its current size
//   file grown or unchanged       -> untouched (growth stays a violation)
function planTighten() {
  const changes = new Map(); // key -> new line count, or null to drop the entry
  for (const [key, baselined] of Object.entries(baseline)) {
    const lines = counts.get(key);
    if (lines === undefined) changes.set(key, null);
    else if (lines > baselined) continue;
    else if (lines <= maxFileLines) changes.set(key, null);
    else if (lines < baselined) changes.set(key, lines);
  }
  return changes;
}

// Rewrite the baseline TEXT in place instead of re-serialising it. The file is
// PowerShell ConvertTo-Json output (4-space indent, two spaces after the
// colon); JSON.stringify would reformat every line and turn this already
// high-conflict file into a merge-conflict magnet. Only changed numbers and
// dropped lines differ, and the original EOL style is kept.
function rewriteBaselineText(text, changes) {
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const entryRe = /^(\s*"((?:[^"\\]|\\.)+)":\s*)(\d+)(,?)(\s*)$/;
  const out = [];
  for (const line of text.split(/\r?\n/)) {
    const m = entryRe.exec(line);
    if (m && changes.has(m[2])) {
      const next = changes.get(m[2]);
      if (next === null) continue;
      out.push(`${m[1]}${next}${m[4]}${m[5]}`);
    } else {
      out.push(line);
    }
  }
  // Dropping the original last entry leaves a dangling comma on the new last
  // one; restore valid JSON.
  const filesStart = out.findIndex((l) => /"files"\s*:\s*\{/.test(l));
  const filesEnd = out.findIndex((l, i) => i > filesStart && /^\s*\}\s*,?\s*$/.test(l));
  for (let i = filesEnd - 1; i > filesStart; i--) {
    if (entryRe.test(out[i])) {
      out[i] = out[i].replace(/,(\s*)$/, '$1');
      break;
    }
  }
  return out.join(eol);
}

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

// --tighten: lower the baseline to the current sizes (never raises an entry).
// Run it in a dedicated PR; see docs/technical/15-quality-gates.md.
if (process.argv.includes('--tighten')) {
  const changes = planTighten();
  if (changes.size === 0) {
    console.log('Baseline already tight - nothing to change.');
  } else {
    const before = computeSlack().total;
    const rewritten = rewriteBaselineText(readFileSync(BASELINE_PATH, 'utf-8'), changes);
    JSON.parse(rewritten); // never write a baseline that does not parse
    writeFileSync(BASELINE_PATH, rewritten);
    let lowered = 0;
    let dropped = 0;
    for (const [key, next] of changes) {
      if (next === null) {
        dropped++;
        console.log(`  - ${key} (was ${baseline[key]}; dropped)`);
        delete baseline[key];
      } else {
        lowered++;
        console.log(`  ${key}: ${baseline[key]} -> ${next}`);
        baseline[key] = next;
      }
    }
    console.log(
      `Tightened ${BASELINE_PATH}: ${lowered} lowered, ${dropped} dropped (slack ${before} -> ${computeSlack().total} lines).`,
    );
  }
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
        `(ratchet protocol — change only this file's entry; bulk lowering belongs in a dedicated --tighten PR). ` +
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

  const slack = computeSlack();
  if (slack.total > 0) {
    console.log(
      `Baseline slack: ${slack.total} lines across ${slack.entries.length} entries ` +
        '(run `node scripts/architecture-check.mjs --tighten` to lock in the gains).',
    );
  }

  // --max-slack[=N]: opt-in gate (default N = 100). Not wired into CI yet.
  const maxSlackFlag = process.argv.find(
    (a) => a === '--max-slack' || a.startsWith('--max-slack='),
  );
  if (maxSlackFlag) {
    const limit = maxSlackFlag.includes('=') ? Number(maxSlackFlag.split('=')[1]) : 100;
    if (!Number.isInteger(limit) || limit < 0) {
      console.error(`Invalid ${maxSlackFlag}: expected a non-negative integer.`);
      process.exit(2);
    }
    if (slack.total > limit) {
      console.error(`Baseline slack ${slack.total} lines exceeds --max-slack=${limit}. Largest:`);
      for (const e of slack.entries.slice(0, 10)) {
        console.error(`  ${e.file}: ${e.lines} lines (baseline: ${e.baselined}, slack ${e.slack})`);
      }
      console.error(
        'Fix: run `node scripts/architecture-check.mjs --tighten` and commit the baseline.',
      );
      process.exit(1);
    }
  }
}
