// electron/__tests__/logPaths.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => '/mock/userData'),
    isPackaged: false,
  },
}));

let originalEnv: Record<string, string | undefined>;
let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logpaths-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR };
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  if (originalEnv.SAGE_LOG_DIR === undefined) delete process.env.SAGE_LOG_DIR;
  else process.env.SAGE_LOG_DIR = originalEnv.SAGE_LOG_DIR;
});

describe('logPaths', () => {
  // Plan amendment 2026-07-02 (after T4 review):
  // SAGE_LOG_DIR is the BASE directory; sage files always go in `${SAGE_LOG_DIR}/logs/`
  // subdirectory. This matches logger.ts T4 behavior and T3 test expectations.
  it('returns SAGE_LOG_DIR/logs when env is set', async () => {
    const { getLogDir } = await import('../logPaths');
    expect(getLogDir()).toBe(join(tmpDir, 'logs'));
  });

  it('creates the directory if it does not exist', async () => {
    const freshDir = join(tmpDir, 'logs-subdir');
    process.env.SAGE_LOG_DIR = freshDir;
    vi.resetModules();

    const { getLogDir } = await import('../logPaths');
    const result = getLogDir();
    expect(result).toBe(join(freshDir, 'logs'));
    expect(existsSync(result)).toBe(true);
  });

  it('falls back to app.getPath("userData")/logs when SAGE_LOG_DIR not set', async () => {
    delete process.env.SAGE_LOG_DIR;
    vi.resetModules();
    const { getLogDir } = await import('../logPaths');
    expect(getLogDir()).toBe(join('/mock/userData', 'logs'));
  });

  it('getCurrentLogFile returns sage-YYYY-MM-DD.ndjson under SAGE_LOG_DIR/logs', async () => {
    const { getCurrentLogFile } = await import('../logPaths');
    const file = getCurrentLogFile();
    expect(file).toBe(join(tmpDir, 'logs', `sage-${new Date().toISOString().slice(0, 10)}.ndjson`));
  });
});
