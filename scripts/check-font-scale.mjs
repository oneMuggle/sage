#!/usr/bin/env node
// scripts/check-font-scale.mjs
//
// U3 font-scale ratchet gate:
// Scans non-test .ts/.tsx files under src/ for hardcoded `text-[Npx]` Tailwind
// classes that bypass the user-configurable `--ui-font-size` scale (`text-ui-2xs`,
// `text-ui-xs`, `text-ui-sm`, etc.).
//
// Usage:
//   node scripts/check-font-scale.mjs                # verify against baseline
//   node scripts/check-font-scale.mjs --max-slack=0  # also fail on any un-tightened slack
//   node scripts/check-font-scale.mjs --tighten      # lower/remove improved entries in baseline

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASELINE_PATH = path.join(ROOT, 'scripts', 'font-scale-baseline.json');
const REGEX = /\btext-\[\d+px\]/g;

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === '__tests__' || entry.name === 'node_modules') continue;
      walk(full, out);
    } else if (
      (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts')) &&
      !entry.name.endsWith('.test.tsx') &&
      !entry.name.endsWith('.test.ts')
    ) {
      out.push(full);
    }
  }
  return out;
}

export function scanFontScaleViolations(rootDir = ROOT) {
  const srcDir = path.join(rootDir, 'src');
  const counts = {};
  for (const file of walk(srcDir)) {
    const rel = path.relative(rootDir, file).replace(/\\/g, '/');
    const text = fs.readFileSync(file, 'utf8');
    const matches = text.match(REGEX);
    if (matches && matches.length > 0) {
      counts[rel] = matches.length;
    }
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
}

function main() {
  const args = process.argv.slice(2);
  const tighten = args.includes('--tighten');
  const slackArg = args.find((a) => a.startsWith('--max-slack='));
  const maxSlack = slackArg ? Number(slackArg.split('=')[1]) : null;

  const actual = scanFontScaleViolations(ROOT);
  const baseline = fs.existsSync(BASELINE_PATH)
    ? JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8')).files ?? {}
    : {};

  if (tighten) {
    const nextFiles = {};
    let lowered = 0;
    let dropped = 0;
    for (const [rel, count] of Object.entries(actual)) {
      nextFiles[rel] = count;
      if (baseline[rel] !== undefined && count < baseline[rel]) lowered++;
    }
    for (const rel of Object.keys(baseline)) {
      if (!(rel in actual)) dropped++;
    }
    const total = Object.values(nextFiles).reduce((a, b) => a + b, 0);
    fs.writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          comment: 'Ratchet baseline for hardcoded text-[Npx] in src/ non-test files (U3). Prefer text-ui-2xs / text-ui-xs / text-ui-sm.',
          total,
          files: nextFiles,
        },
        null,
        2,
      ) + '\n',
      'utf8',
    );
    console.log(`Tightened font-scale-baseline.json: ${lowered} lowered, ${dropped} dropped (total=${total}).`);
    return;
  }

  const regressions = [];
  let slack = 0;
  for (const [rel, count] of Object.entries(actual)) {
    const allowed = baseline[rel] ?? 0;
    if (count > allowed) {
      regressions.push(`  ${rel}: ${count} > baseline ${allowed}`);
    } else if (count < allowed) {
      slack += allowed - count;
    }
  }
  for (const [rel, allowed] of Object.entries(baseline)) {
    if (!(rel in actual)) {
      slack += allowed;
    }
  }

  if (regressions.length > 0) {
    console.error('Hardcoded text-[Npx] regression detected (use text-ui-2xs / text-ui-xs / text-ui-sm):\n' + regressions.join('\n'));
    process.exit(1);
  }
  if (maxSlack !== null && slack > maxSlack) {
    console.error(`Font-scale baseline slack ${slack} exceeds --max-slack=${maxSlack}. Run: node scripts/check-font-scale.mjs --tighten`);
    process.exit(1);
  }
  const total = Object.values(actual).reduce((a, b) => a + b, 0);
  console.log(`Font-scale check passed (${total} baselined occurrences across ${Object.keys(actual).length} files, slack=${slack}).`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
