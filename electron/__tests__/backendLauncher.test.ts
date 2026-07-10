// electron/__tests__/backendLauncher.test.ts
import { describe, it, expect } from 'vitest';
import { resolveBackendLaunchCommand, type ResolveOpts } from '../backendLauncher';

/**
 * Helper: build minimal ResolveOpts for one test, then override.
 * Bundled-Python existence is staged via `existsSyncFn` so we never touch disk.
 */
function makeOpts(overrides: Partial<ResolveOpts> = {}): ResolveOpts {
  return {
    env: {},
    resourcesPath: '/mock/resources',
    platform: 'win32',
    isPackaged: true,
    sageDbPath: '/mock/sage.db',
    port: 8765,
    existsSyncFn: () => false,
    ...overrides,
  };
}

describe('resolveBackendLaunchCommand', () => {
  // ─────────────── Dev branch ─────────────────────────────────────────────

  describe('dev (isPackaged=false)', () => {
    it('uses `conda run -n sage-backend python -m backend.main` by default', () => {
      const plan = resolveBackendLaunchCommand(makeOpts({ isPackaged: false }));
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'conda',
        args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'],
        reason: 'dev-conda',
      });
      // No PYTHONPATH in dev (conda handles it via env name)
      if (plan.kind === 'spawn') {
        expect(plan.extraEnv).toEqual({ SAGE_DB_PATH: '/mock/sage.db' });
        expect(plan.extraEnv).not.toHaveProperty('PYTHONPATH');
      }
    });

    it('honors SAGE_PYTHON env override (e.g. "python3") for power devs', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({ isPackaged: false, env: { SAGE_PYTHON: 'python3' } }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'python3',
        reason: 'dev-conda-overridden',
      });
    });

    it('ignores resourcesPath in dev even if provided', () => {
      // Defensive: dev mode should NEVER use bundled Python. If resourcesPath
      // accidentally contains python.exe and the env says packaged=false,
      // we still go to conda.
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          isPackaged: false,
          resourcesPath: '/mock/resources',
          existsSyncFn: () => true, // pretend bundled python exists
        }),
      );
      expect(plan).toMatchObject({ kind: 'spawn', cmd: 'conda' });
    });
  });

  // ─────────────── Packaged Win32 ────────────────────────────────────────

  describe('packaged win32', () => {
    it('uses bundled python.exe when present', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          existsSyncFn: (p) => p.endsWith('python.exe'),
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: '/mock/resources/python/python.exe',
        args: [
          '-m',
          'uvicorn',
          'backend.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          '8765',
        ],
        reason: 'packaged-win32-bundled',
      });
      if (plan.kind === 'spawn') {
        expect(plan.extraEnv).toEqual({
          SAGE_DB_PATH: '/mock/sage.db',
          // Win uses ';' as PYTHONPATH separator
          PYTHONPATH: '/mock/resources/backend;/mock/resources/sage-core',
        });
      }
    });

    it('returns broken-installer when bundled python.exe missing (NEVER falls back to conda)', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          existsSyncFn: () => false,
        }),
      );
      expect(plan).toMatchObject({
        kind: 'broken-installer',
        reason: 'packaged-win32-missing-python',
      });
      if (plan.kind === 'broken-installer') {
        expect(plan.title).toContain('Python');
        expect(plan.detail).toContain('python.exe');
        expect(plan.detail).toContain('releases');
        // The "fall back to conda" anti-pattern must NOT happen here.
        // If we ever reintroduce it, this assertion catches it.
        expect(plan.reason).not.toBe('dev-conda');
      }
    });

    it('passes port from opts through to uvicorn args', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          port: 9999,
          existsSyncFn: (p) => p.endsWith('python.exe'),
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        args: expect.arrayContaining(['--port', '9999']),
      });
    });
  });

  // ─────────────── Packaged Linux ────────────────────────────────────────

  describe('packaged linux', () => {
    it('uses bundled python3 binary at resources/python/bin/python3', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'linux',
          isPackaged: true,
          existsSyncFn: (p) => p.endsWith('python3'),
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: '/mock/resources/python/bin/python3',
        reason: 'packaged-linux-bundled',
      });
      if (plan.kind === 'spawn') {
        // Linux uses ':' as PYTHONPATH separator (not ';')
        expect(plan.extraEnv.PYTHONPATH).toBe('/mock/resources/backend:/mock/resources/sage-core');
      }
    });

    it('returns broken-installer when bundled python3 missing', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'linux',
          isPackaged: true,
          existsSyncFn: () => false,
        }),
      );
      expect(plan).toMatchObject({
        kind: 'broken-installer',
        reason: 'packaged-linux-missing-python',
      });
    });
  });

  // ─────────────── Packaged macOS ────────────────────────────────────────

  describe('packaged darwin', () => {
    it('returns broken-installer (macOS not bundled today)', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'darwin',
          isPackaged: true,
          // Even if python exists, mac not supported per electron-builder.yml
          existsSyncFn: () => true,
        }),
      );
      expect(plan).toMatchObject({
        kind: 'broken-installer',
        reason: 'packaged-macos-unsupported',
      });
      if (plan.kind === 'broken-installer') {
        expect(plan.title).toContain('macOS');
        // macOS instruction points users to the README / source build path,
        // not the GitHub releases page (releases don't exist for darwin yet).
        expect(plan.detail).toContain('git clone');
      }
    });
  });

  // ─────────────── Packaged but no resourcesPath ─────────────────────────

  describe('packaged but resourcesPath undefined', () => {
    it('returns broken-installer', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({ isPackaged: true, resourcesPath: undefined }),
      );
      expect(plan).toMatchObject({
        kind: 'broken-installer',
        reason: 'packaged-no-resources-path',
      });
    });
  });

  // ─────────────── Packaged unknown platform ─────────────────────────────

  describe('packaged unknown platform', () => {
    it('returns broken-installer for unsupported platforms', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'freebsd' as NodeJS.Platform,
          isPackaged: true,
          existsSyncFn: () => true,
        }),
      );
      expect(plan.kind).toBe('broken-installer');
      // The reason is one of the literal union members of `broken-installer`.
      expect((plan as Extract<typeof plan, { kind: 'broken-installer' }>).reason).toBe(
        'packaged-unknown-platform',
      );
    });
  });

  // ─────────────── Regression: the original bug ──────────────────────────

  describe('regression: packaged Win32 with missing bundled python must NOT spawn conda', () => {
    it('does not produce a spawn plan with cmd "conda"', () => {
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          existsSyncFn: () => false, // bundled python missing
        }),
      );
      // This is the assertion that captures the bug: in the original code
      // this returned spawn('conda', ...) which crashed end-user Windows
      // installations with "spawn conda ENOENT".
      if (plan.kind === 'spawn') {
        expect(plan.cmd).not.toBe('conda');
      } else {
        expect(plan.kind).toBe('broken-installer');
      }
    });
  });
});
