// electron/__tests__/backendLauncher.test.ts
import { describe, it, expect } from 'vitest';
import { join } from 'node:path';
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
    sageUserDataDir: '/mock/userData',
    port: 8765,
    existsSyncFn: () => false,
    ...overrides,
  };
}

describe('resolveBackendLaunchCommand', () => {
  // ─────────────── Dev branch ─────────────────────────────────────────────

  describe('dev (isPackaged=false)', () => {
    it('uses `conda run -n sage-backend python -m backend.main` by default', () => {
      // Default = no CONDA_PREFIX (CI sandbox or power dev running outside
      // a conda env). Must still use the legacy `conda run -n` wrapper.
      const plan = resolveBackendLaunchCommand(makeOpts({ isPackaged: false }));
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'conda',
        args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'],
        reason: 'dev-conda',
      });
      // No PYTHONPATH in dev (conda handles it via env name)
      if (plan.kind === 'spawn') {
        expect(plan.extraEnv).toEqual({
          SAGE_DB_PATH: '/mock/sage.db',
          SAGE_USER_DATA_DIR: '/mock/userData',
        });
        expect(plan.extraEnv).not.toHaveProperty('PYTHONPATH');
      }
    });

    it('uses ${CONDA_PREFIX}/bin/python directly when CONDA_PREFIX is set (avoids conda-run wrapper pid mismatch)', () => {
      // Regression guard for the dev-mode "后端服务在 30 秒内未响应"
      // dialog: `conda run -n sage-backend python` spawns a 3-deep
      // process tree (conda → bash → python) so child_process.spawn's
      // ``proc.pid`` is the conda wrapper, not the python child. The
      // backend's ``/health/proof`` returns ``os.getpid()``, so
      // ``ownsBackend`` (``health.pid === ownership.pid``) always fails
      // and the supervisor times out 90s later. Invoking the env's
      // python binary directly makes ``proc.pid`` == the python PID
      // and the check passes.
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          isPackaged: false,
          platform: 'linux',
          env: { CONDA_PREFIX: '/opt/anaconda3/envs/sage-backend' },
          existsSyncFn: (p) => p === '/opt/anaconda3/envs/sage-backend/bin/python',
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: '/opt/anaconda3/envs/sage-backend/bin/python',
        args: ['-m', 'backend.main'],
        reason: 'dev-conda',
      });
      if (plan.kind === 'spawn') {
        expect(plan.extraEnv).toEqual({
          SAGE_DB_PATH: '/mock/sage.db',
          SAGE_USER_DATA_DIR: '/mock/userData',
          PYTHON_BACKEND_PORT: '8765',
        });
        // CRITICAL: must NOT include `run`, `-n`, or `sage-backend` —
        // that's the legacy conda-wrapper shape and it would re-introduce
        // the pid mismatch.
        expect(plan.args).not.toContain('run');
        expect(plan.args).not.toContain('-n');
        expect(plan.args).not.toContain('sage-backend');
      }
    });

    it('uses windows python.exe directly when CONDA_PREFIX is set on win32', () => {
      // Symmetric guard for the win32 dev branch: ``condaEnvPythonPath``
      // joins ``python.exe`` directly under the prefix (Windows conda
      // envs don't nest it under ``bin/``). Note: we use literal
      // backslashes here, NOT ``path.win32.join`` — the source uses
      // string concatenation so the output preserves whatever separator
      // the caller passed in (real conda on Windows reports backslash
      // paths, on linux forward-slash).
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          isPackaged: false,
          platform: 'win32',
          env: { CONDA_PREFIX: 'C:\\Users\\dev\\anaconda3\\envs\\sage-backend' },
          existsSyncFn: (p) => p === 'C:\\Users\\dev\\anaconda3\\envs\\sage-backend\\python.exe',
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'C:\\Users\\dev\\anaconda3\\envs\\sage-backend\\python.exe',
        args: ['-m', 'backend.main'],
        reason: 'dev-conda',
      });
    });

    it('falls back to `conda run -n sage-backend` when CONDA_PREFIX is set but the env python is missing', () => {
      // Defensive: if the user has CONDA_PREFIX pointing at a partially
      // constructed env (or a Windows env that hasn't been bootstrapped
      // yet), the launcher must not silently produce a broken spawn —
      // fall through to the legacy `conda run -n` path, which will fail
      // loudly if conda itself can't find the env.
      const plan = resolveBackendLaunchCommand(
        makeOpts({
          isPackaged: false,
          platform: 'linux',
          env: { CONDA_PREFIX: '/opt/empty/env' },
          existsSyncFn: () => false,
        }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'conda',
        args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'],
        reason: 'dev-conda',
      });
    });

    it('honors SAGE_PYTHON env override (e.g. "python3") for power devs', () => {
      // When SAGE_PYTHON is set, we treat it as a raw interpreter that already
      // has `backend` and `sage_core` importable. Args drop the conda
      // subcommand shell and go straight to `-m backend.main`, the same entry
      // dev-conda uses — so the `__main__` block (and setup_logging()) runs.
      const plan = resolveBackendLaunchCommand(
        makeOpts({ isPackaged: false, env: { SAGE_PYTHON: 'python3' } }),
      );
      expect(plan).toMatchObject({
        kind: 'spawn',
        cmd: 'python3',
        args: ['-m', 'backend.main'],
        reason: 'dev-conda-overridden',
      });
      if (plan.kind === 'spawn') {
        // Regression guard (AI review L2): SAGE_USER_DATA_DIR must travel with
        // the dev branches, not only packaged. Without this assertion an
        // accidental drop in dev-conda-overridden's extraEnv would silently
        // regress dev installs to the bundled fallback path.
        expect(plan.extraEnv).toEqual({
          SAGE_DB_PATH: '/mock/sage.db',
          SAGE_USER_DATA_DIR: '/mock/userData',
          PYTHON_BACKEND_PORT: '8765',
        });
        expect(plan.extraEnv).not.toHaveProperty('PYTHONPATH');
      }
    });

    it('does NOT pair SAGE_PYTHON with conda-flavoured args (no `run -n` regression)', () => {
      // Regression guard for issue #6 of PR #130. Old behaviour: any cmd
      // value (e.g. "python3") was paired with
      // ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'] which
      // produces `python3 run -n ...` and dies with "no such subcommand".
      const plan = resolveBackendLaunchCommand(
        makeOpts({ isPackaged: false, env: { SAGE_PYTHON: 'python3' } }),
      );
      if (plan.kind === 'spawn') {
        expect(plan.args).not.toContain('run');
        expect(plan.args).not.toContain('-n');
        expect(plan.args).not.toContain('sage-backend');
      }
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
        cmd: join('/mock', 'resources', 'python', 'python.exe'),
        args: ['-m', 'backend.main'],
        reason: 'packaged-win32-bundled',
      });
      if (plan.kind === 'spawn') {
        expect(plan.extraEnv).toEqual({
          SAGE_DB_PATH: '/mock/sage.db',
          SAGE_USER_DATA_DIR: '/mock/userData',
          // test env has no SAGE_LOG_LEVEL set → `?? 'info'` fallback applies
          SAGE_LOG_LEVEL: 'info',
          // Win uses ';' as PYTHONPATH separator
          PYTHONPATH: [join('/mock', 'resources', 'backend'), join('/mock', 'resources', 'sage-core')].join(';'),
          PYTHON_BACKEND_PORT: '8765',
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

    it('passes port via PYTHON_BACKEND_PORT env (not CLI args)', () => {
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
        cmd: join('/mock', 'resources', 'python', 'python.exe'),
        args: ['-m', 'backend.main'],
      });
      if (plan.kind === 'spawn') {
        // Port now travels via PYTHON_BACKEND_PORT env — backend/main.py's
        // `__main__` block reads it — not via uvicorn `--port` CLI args.
        expect(plan.extraEnv.PYTHON_BACKEND_PORT).toBe('9999');
        expect(plan.args).not.toContain('--port');
      }
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
        cmd: join('/mock', 'resources', 'python', 'bin', 'python3'),
        reason: 'packaged-linux-bundled',
      });
      if (plan.kind === 'spawn') {
        // Linux uses ':' as PYTHONPATH separator (not ';')
        expect(plan.extraEnv.PYTHONPATH).toBe([join('/mock', 'resources', 'backend'), join('/mock', 'resources', 'sage-core')].join(':'));
        // Port travels via PYTHON_BACKEND_PORT env on packaged linux too
        expect(plan.extraEnv.PYTHON_BACKEND_PORT).toBe('8765');
        expect(plan.args).toEqual(['-m', 'backend.main']);
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
