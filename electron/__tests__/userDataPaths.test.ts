// electron/__tests__/userDataPaths.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { join } from 'node:path';

/**
 * Lock down the SAGE_DB_PATH / SAGE_USER_DATA_DIR resolution so the
 * backend spawn path and the doctor spawn path stay in sync.
 *
 * Regression test for the 2026-09-08 Win7 launch incident:
 *   - backend spawn (main.ts:278-285) computed sageUserDataDir with
 *     `app.isPackaged ? app.getPath('userData') : process.cwd()/data`
 *   - doctor spawn (main.ts:1642-1643) used
 *     `process.env.SAGE_USER_DATA_DIR ?? process.cwd()/data`
 *     — NO isPackaged branch, so on a packaged Win7 install where
 *     process.cwd() resolves to the install dir (e.g.
 *     C:\Program Files\Sage), the doctor subprocess probed
 *     Program Files instead of %APPDATA%\Sage, producing 3
 *     false-positive CRITICAL verdicts.
 *
 * Both call sites now resolve through these helpers, so the bug
 * cannot recur without breaking both tests at once.
 */

const MOCK_USER_DATA = '/mock/electron/userData';
const MOCK_CWD = '/mock/cwd';

let isPackagedRef = true;

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn((name: string) => {
      if (name === 'userData') return '/mock/electron/userData';
      throw new Error(`unexpected getPath(${name}) in test`);
    }),
    get isPackaged() {
      return isPackagedRef;
    },
  },
}));

let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  originalEnv = {
    SAGE_DB_PATH: process.env.SAGE_DB_PATH,
    SAGE_USER_DATA_DIR: process.env.SAGE_USER_DATA_DIR,
  };
  delete process.env.SAGE_DB_PATH;
  delete process.env.SAGE_USER_DATA_DIR;
  isPackagedRef = true;
  // Pin process.cwd() to a known value for deterministic assertions.
  vi.spyOn(process, 'cwd').mockReturnValue(MOCK_CWD);
});

afterEach(() => {
  for (const [k, v] of Object.entries(originalEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  vi.restoreAllMocks();
});

describe('resolveSageDbPath', () => {
  it('honors explicit SAGE_DB_PATH over all defaults', async () => {
    process.env.SAGE_DB_PATH = '/env/db.sqlite';
    isPackagedRef = true;
    const { resolveSageDbPath } = await import('../userDataPaths');
    expect(resolveSageDbPath()).toBe('/env/db.sqlite');
  });

  it('uses app.getPath("userData")/sage.db when packaged', async () => {
    isPackagedRef = true;
    const { resolveSageDbPath } = await import('../userDataPaths');
    expect(resolveSageDbPath()).toBe(join(MOCK_USER_DATA, 'sage.db'));
  });

  it('falls back to <cwd>/data/sage.db when dev (isPackaged=false)', async () => {
    isPackagedRef = false;
    const { resolveSageDbPath } = await import('../userDataPaths');
    expect(resolveSageDbPath()).toBe(join(MOCK_CWD, 'data', 'sage.db'));
  });
});

describe('resolveSageUserDataDir', () => {
  it('honors explicit SAGE_USER_DATA_DIR over all defaults', async () => {
    process.env.SAGE_USER_DATA_DIR = '/env/userdata';
    isPackagedRef = true;
    const { resolveSageUserDataDir } = await import('../userDataPaths');
    expect(resolveSageUserDataDir()).toBe('/env/userdata');
  });

  it('uses app.getPath("userData") when packaged — the Win7 fix', async () => {
    // Regression: pre-fix doctor spawn path used `process.cwd()/data`
    // unconditionally on packaged Win7, producing the false-positive
    // sqlite_writable CRITICAL on Program Files installs.
    isPackagedRef = true;
    const { resolveSageUserDataDir } = await import('../userDataPaths');
    expect(resolveSageUserDataDir()).toBe(MOCK_USER_DATA);
  });

  it('falls back to <cwd>/data when dev (isPackaged=false)', async () => {
    isPackagedRef = false;
    const { resolveSageUserDataDir } = await import('../userDataPaths');
    expect(resolveSageUserDataDir()).toBe(join(MOCK_CWD, 'data'));
  });
});