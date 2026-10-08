// @vitest-environment node
//
// architecture-check.mjs is a CLI that reads architecture-policy.json /
// architecture-baseline.json relative to the cwd and walks '.', so every test
// builds a tiny throwaway project (maxFileLines = 5) and spawns the real script.
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT = fileURLToPath(new URL('../architecture-check.mjs', import.meta.url));

/** Source text whose architecture-check line count (split('\n').length) is exactly n. */
const fileOf = (n) => Array.from({ length: n }, (_, i) => `// line ${i + 1}`).join('\n');

/**
 * Same shape as the committed baseline (PowerShell ConvertTo-Json output:
 * 4-space indent, two spaces after the colon, entries indented by 18).
 */
function baselineText(entries, eol = '\n') {
  const body = Object.entries(entries)
    .map(([k, v]) => `                  "${k}":  ${v}`)
    .join(`,${eol}`);
  return (
    ['{', '    "version":  1,', '    "files":  {', body, '              }', '}'].join(eol) + eol
  );
}

let dir;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'archcheck-'));
  mkdirSync(join(dir, 'src'));
  writeFileSync(
    join(dir, 'architecture-policy.json'),
    JSON.stringify({ global: { maxFileLines: 5 } }),
  );
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const put = (rel, lines) => writeFileSync(join(dir, rel), fileOf(lines));
const setBaseline = (entries, eol) =>
  writeFileSync(join(dir, 'architecture-baseline.json'), baselineText(entries, eol));
const baselineFile = () => readFileSync(join(dir, 'architecture-baseline.json'), 'utf-8');
const run = (...args) =>
  spawnSync(process.execPath, [SCRIPT, ...args], { cwd: dir, encoding: 'utf-8' });

describe('architecture-check ratchet (existing semantics)', () => {
  it('flags a new file over the limit and a baselined file that grew', () => {
    put('src/new.ts', 9); // not baselined, > 5
    put('src/grown.ts', 9); // baselined at 7
    setBaseline({ 'src/grown.ts': 7 });
    const r = run();
    expect(r.status).toBe(1);
    expect(r.stderr).toContain('1 NEW files exceeding 5 lines');
    expect(r.stderr).toContain('1 BASELINED files that have grown');
  });

  it('passes when nothing is over its limit', () => {
    put('src/ok.ts', 5);
    put('src/big.ts', 8);
    setBaseline({ 'src/big.ts': 8 });
    const r = run();
    expect(r.status).toBe(0);
    expect(r.stdout).toContain('All files within limits (1 baselined, 5-line max for new files).');
    expect(r.stdout).not.toContain('Baseline slack');
  });
});

describe('architecture-check --tighten', () => {
  it('lowers entries to the current size, drops paid-off and dead entries, never raises', () => {
    put('src/big.ts', 12); // baseline 20 -> lowered to 12
    put('src/paid.ts', 4); // baseline 10, now <= 5 -> dropped
    put('src/same.ts', 8); // baseline 8 -> untouched
    put('src/grown.ts', 9); // baseline 7 -> grown: untouched, stays a violation
    setBaseline({
      'src/big.ts': 20,
      'src/dead.ts': 9,
      'src/grown.ts': 7,
      'src/paid.ts': 10,
      'src/same.ts': 8,
    });

    const r = run('--tighten');

    expect(baselineFile()).toBe(
      baselineText({ 'src/big.ts': 12, 'src/grown.ts': 7, 'src/same.ts': 8 }),
    );
    expect(r.stdout).toContain('1 lowered, 2 dropped (slack 14 -> 0 lines)');
    expect(r.status).toBe(1); // tightening must not hide the grown file
  });

  it('keeps the file format byte-for-byte except the changed lines (LF and CRLF)', () => {
    put('src/a.ts', 12);
    put('src/b.ts', 9);
    for (const eol of ['\n', '\r\n']) {
      setBaseline({ 'src/a.ts': 30, 'src/b.ts': 9 }, eol);
      expect(run('--tighten').status).toBe(0);
      expect(baselineFile()).toBe(baselineText({ 'src/a.ts': 12, 'src/b.ts': 9 }, eol));
    }
  });

  it('removes the dangling comma when the last entry is dropped', () => {
    put('src/a.ts', 12);
    put('src/z.ts', 3);
    setBaseline({ 'src/a.ts': 12, 'src/z.ts': 40 });
    expect(run('--tighten').status).toBe(0);
    const text = baselineFile();
    expect(() => JSON.parse(text)).not.toThrow();
    expect(JSON.parse(text).files).toEqual({ 'src/a.ts': 12 });
  });

  it('is idempotent', () => {
    put('src/a.ts', 12);
    setBaseline({ 'src/a.ts': 30 });
    run('--tighten');
    const once = baselineFile();
    const r = run('--tighten');
    expect(r.stdout).toContain('already tight');
    expect(baselineFile()).toBe(once);
  });
});

describe('architecture-check slack reporting', () => {
  it('reports slack in the normal run without failing it', () => {
    put('src/a.ts', 12);
    setBaseline({ 'src/a.ts': 30 });
    const r = run();
    expect(r.status).toBe(0);
    expect(r.stdout).toContain('Baseline slack: 18 lines across 1 entries');
  });

  it('--max-slack fails above the limit and passes at or below it', () => {
    put('src/a.ts', 12);
    setBaseline({ 'src/a.ts': 30 }); // slack 18
    expect(run('--max-slack=17').status).toBe(1);
    expect(run('--max-slack=18').status).toBe(0);
    expect(run('--max-slack').status).toBe(0); // bare flag: default limit 100
    expect(run('--tighten', '--max-slack=0').status).toBe(0); // tightening first leaves no slack
  });

  it('rejects an invalid --max-slack value', () => {
    put('src/a.ts', 3);
    setBaseline({});
    expect(run('--max-slack=abc').status).toBe(2);
    expect(run('--max-slack=-1').status).toBe(2);
  });
});
