// electron/__tests__/logRotate.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync, utimesSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => '/mock/userData'),
    isPackaged: false,
  },
}));

let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-rotate-test-'));
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  delete process.env.SAGE_LOG_DIR;
});

function fileAgeDays(file: string, days: number): void {
  const mtime = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  utimesSync(file, mtime, mtime);
}

describe('logRotate.cleanupOlderThan', () => {
  it('removes files older than N days', async () => {
    // T6 amendment: SAGE_LOG_DIR is BASE; sage log files live in ${SAGE_LOG_DIR}/logs/.
    const logDir = join(tmpDir, 'logs');
    mkdirSync(logDir, { recursive: true });
    const oldFile = join(logDir, 'sage-2020-01-01.ndjson');
    const recentFile = join(logDir, 'sage-2026-07-02.ndjson');
    writeFileSync(oldFile, '{}\n');
    writeFileSync(recentFile, '{}\n');
    fileAgeDays(oldFile, 10);
    fileAgeDays(recentFile, 1);

    const { cleanupOlderThan } = await import('../logRotate');
    cleanupOlderThan(7);

    expect(existsSync(oldFile)).toBe(false);
    expect(existsSync(recentFile)).toBe(true);
  });

  it('does not delete non-ndjson files', async () => {
    const logDir = join(tmpDir, 'logs');
    mkdirSync(logDir, { recursive: true });
    const oldTxt = join(logDir, 'notes.txt');
    writeFileSync(oldTxt, 'do not delete');
    fileAgeDays(oldTxt, 30);

    const { cleanupOlderThan } = await import('../logRotate');
    cleanupOlderThan(7);

    expect(existsSync(oldTxt)).toBe(true);
  });

  it('does not throw on empty or missing directory', async () => {
    delete process.env.SAGE_LOG_DIR;
    vi.resetModules();
    const { cleanupOlderThan } = await import('../logRotate');
    expect(() => cleanupOlderThan(7)).not.toThrow();
  });
});