// electron/__tests__/backendLauncher.test.ts
import { describe, it, expect } from 'vitest';
import { join } from 'node:path';
import {
  resolveBackendLaunchCommand,
  resolveDoctorLaunchCommand,
  type ResolveOpts,
} from '../backendLauncher';

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
          // 2026-08-26: dev-conda now threads PYTHON_BACKEND_PORT so the
          // conda-launched backend reads the same port main.ts tells the
          // renderer to hit (previously it fell back to the backend's
          // built-in default 8765 regardless of override → ECONNREFUSED).
          PYTHON_BACKEND_PORT: '8765',
        });
        expect(plan.extraEnv).not.toHaveProperty('PYTHONPATH');
      }
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
          PYTHONPATH: [
            join('/mock', 'resources', 'backend'),
            join('/mock', 'resources', 'sage-core'),
          ].join(';'),
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
        expect(plan.extraEnv.PYTHONPATH).toBe(
          [join('/mock', 'resources', 'backend'), join('/mock', 'resources', 'sage-core')].join(
            ':',
          ),
        );
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

  // ─────────────── Doctor argv derivation (2026-08-26) ───────────────────
  //
  // Why a separate resolver:
  //   The doctor subprocess needs the EXACT same argv/env as the backend
  //   supervisor — except the entry-point flips from `backend.main` to
  //   `backend.cli.doctor`. Sharing one resolver keeps both paths from
  //   drifting (which previously produced `conda -m backend.cli.doctor ...`
  //   in the dev branch: conda has no `-m` subcommand).
  //
  // What the assertions lock down:
  //   1. dev-conda: command is `conda`, args preserve the full
  //      `run -n sage-backend python -m backend.cli.doctor --json` chain.
  //   2. dev-conda-overridden: command is the raw override (e.g. "python3"),
  //      args = `['-m', 'backend.cli.doctor', '--json']` — no conda shell.
  //   3. packaged-*-bundled: command is the bundled interpreter, args end
  //      with `backend.cli.doctor --json` (NOT `backend.main`).
  //   4. broken-installer → undefined (caller falls back to bare doctor).
  //   5. env must include the same SAGE_DB_PATH / SAGE_USER_DATA_DIR /
  //      PYTHON_BACKEND_PORT keys the backend would see — doctor probes the
  //      supervisor's exact context, not a stripped-down one.

  describe('resolveDoctorLaunchCommand (2026-08-26)', () => {
    it('dev-conda: command=conda, args end with backend.cli.doctor --json', () => {
      const doctorPlan = resolveDoctorLaunchCommand(makeOpts({ isPackaged: false }));
      expect(doctorPlan).toMatchObject({
        command: 'conda',
        args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.cli.doctor', '--json'],
        reason: 'dev-conda',
      });
      // Regression guard: the OLD bug was doctor.ts hard-coding
      // `['-m', 'backend.cli.doctor', '--json']` and main.ts passing
      // `pythonBin=conda` — that produced `conda -m backend.cli.doctor --json`.
      if (doctorPlan) {
        expect(doctorPlan.command).toBe('conda');
        expect(doctorPlan.args[0]).toBe('run');
      }
    });

    it('dev-conda-overridden: command=SAGE_PYTHON, args drop conda shell', () => {
      const doctorPlan = resolveDoctorLaunchCommand(
        makeOpts({ isPackaged: false, env: { SAGE_PYTHON: 'python3' } }),
      );
      expect(doctorPlan).toMatchObject({
        command: 'python3',
        args: ['-m', 'backend.cli.doctor', '--json'],
        reason: 'dev-conda-overridden',
      });
    });

    it('packaged-win32: command=bundled python.exe, args include doctor entry', () => {
      const doctorPlan = resolveDoctorLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          existsSyncFn: (p) => p.endsWith('python.exe'),
        }),
      );
      expect(doctorPlan).toMatchObject({
        command: join('/mock', 'resources', 'python', 'python.exe'),
        args: ['-m', 'backend.cli.doctor', '--json'],
        reason: 'packaged-win32-bundled',
      });
      // Must NOT spawn the backend entry-point by mistake.
      if (doctorPlan) {
        expect(doctorPlan.args).not.toContain('backend.main');
      }
    });

    it('packaged-linux: command=bundled python3, args include doctor entry', () => {
      const doctorPlan = resolveDoctorLaunchCommand(
        makeOpts({
          platform: 'linux',
          isPackaged: true,
          existsSyncFn: (p) => p.endsWith('python3'),
        }),
      );
      expect(doctorPlan).toMatchObject({
        command: join('/mock', 'resources', 'python', 'bin', 'python3'),
        args: ['-m', 'backend.cli.doctor', '--json'],
        reason: 'packaged-linux-bundled',
      });
    });

    it('returns undefined for broken-installer (caller falls back)', () => {
      const doctorPlan = resolveDoctorLaunchCommand(
        makeOpts({
          platform: 'win32',
          isPackaged: true,
          existsSyncFn: () => false,
        }),
      );
      expect(doctorPlan).toBeUndefined();
    });

    it('env carries SAGE_DB_PATH / SAGE_USER_DATA_DIR / PYTHON_BACKEND_PORT', () => {
      const doctorPlan = resolveDoctorLaunchCommand(makeOpts({ isPackaged: false }));
      expect(doctorPlan).toBeDefined();
      if (doctorPlan) {
        // Dev branch: conda env name carries PYTHONPATH, but the
        // supervisor-relevant env keys (db / user-data / port) MUST travel
        // so doctor probes the same env the backend will see.
        expect(doctorPlan.env.SAGE_DB_PATH).toBe('/mock/sage.db');
        expect(doctorPlan.env.SAGE_USER_DATA_DIR).toBe('/mock/userData');
        expect(doctorPlan.env.PYTHON_BACKEND_PORT).toBe('8765');
      }
    });

    it('dev branch includes PYTHON_BACKEND_PORT (regression guard)', () => {
      // Round-2 fast-follow: dev-conda plan in backendLauncher.test.ts
      // asserts env has only SAGE_DB_PATH + SAGE_USER_DATA_DIR — but the
      // plan used by runBackend DOES include PYTHON_BACKEND_PORT via the
      // `env` field (separate from extraEnv). Doctor must mirror that —
      // otherwise the doctor subprocess reads a different port than the
      // backend spawn, defeating its pre-launch probe.
      const doctorPlan = resolveDoctorLaunchCommand(makeOpts({ isPackaged: false }));
      expect(doctorPlan).toBeDefined();
      if (doctorPlan) {
        expect(doctorPlan.env.PYTHON_BACKEND_PORT).toBe('8765');
      }
    });
  });
});
