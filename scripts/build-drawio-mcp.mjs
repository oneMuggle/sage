#!/usr/bin/env node
/**
 * Build the bundled draw.io MCP server (packages/drawio-mcp-server).
 *
 * PUPPETEER_SKIP_DOWNLOAD=1 is set for the install step: the server resolves a
 * browser at runtime via CHROME_PATH / PUPPETEER_EXECUTABLE_PATH, so the ~150 MB
 * Chromium download is dead weight in CI and packaging. Cross-platform alternative
 * to an inline POSIX-only `VAR=1 npm ...` script.
 */
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PREFIX = join(ROOT, 'packages', 'drawio-mcp-server');
const isWin = process.platform === 'win32';
const npm = isWin ? 'npm.cmd' : 'npm';

const env = { ...process.env, PUPPETEER_SKIP_DOWNLOAD: '1' };

const steps = [
  ['ci', '--no-audit', '--no-fund'],
  ['run', 'build'],
];

for (const args of steps) {
  const result = spawnSync(npm, ['--prefix', PREFIX, ...args], {
    stdio: 'inherit',
    env,
    shell: isWin,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
