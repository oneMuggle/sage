/**
 * Backend launcher resolution — pure function.
 *
 * Decides which command + args to use to launch the Python FastAPI backend.
 * Lives separately from main.ts so it can be unit-tested without booting
 * Electron — main.ts does the I/O (spawn, dialogs, logging), this file
 * only chooses.
 *
 * Decision tree:
 *   dev  (isPackaged=false)
 *     → SAGE_PYTHON env set: use that interpreter directly with -m backend.main
 *       (e.g. power devs running `pip install -e` into a system Python)
 *     → CONDA_PREFIX env set + env python present:
 *       invoke ${CONDA_PREFIX}/bin/python (or python.exe on win32) directly.
 *       This avoids the 3-deep `conda run` wrapper tree, which would make
 *       ``child_process.spawn``'s ``proc.pid`` the conda wrapper rather than
 *       the actual python child and trip the ``ownsBackend`` pid check in
 *       ``waitForBackend``. See the inline comment in
 *       ``resolveBackendLaunchCommand`` for full rationale.
 *     → fallback (CI / outside any conda env):
 *       `conda run -n sage-backend python -m backend.main`
 *
 *   packaged win32
 *     → resourcesPath/python/python.exe + PYTHONPATH for backend/sage-core
 *     → if missing: broken-installer (NEVER fall back to `conda`; end-user
 *       machines do not have conda, and silently spawning it produces the
 *       opaque "spawn conda ENOENT" JavaScript crash that buries the real
 *       cause)
 *
 *   packaged linux
 *     → resourcesPath/python/bin/python3 + PYTHONPATH for backend/sage-core
 *     → if missing: broken-installer
 *
 *   packaged darwin
 *     → broken-installer (electron-builder.yml mac.target: null;
 *       macOS not bundled today)
 *
 *   packaged other
 *     → broken-installer (unknown platform; not bundled)
 */

import { existsSync as defaultExistsSync } from 'node:fs';
import { join } from 'node:path';

export interface ResolveOpts {
  /** process.env snapshot at call time — used for SAGE_PYTHON + dev branch detection */
  env: NodeJS.ProcessEnv;
  /** Electron's process.resourcesPath in production; undefined in dev */
  resourcesPath: string | undefined;
  /** process.platform snapshot */
  platform: NodeJS.Platform;
  /** app.isPackaged snapshot */
  isPackaged: boolean;
  /** Resolved SAGE_DB_PATH — caller computes (may depend on app.getPath) */
  sageDbPath: string;
  /** Resolved SAGE_USER_DATA_DIR — per-user writable location for runtime-mutable
   *  backend artifacts (themes, scheduled-tasks JSON, log files). Caller computes
   *  (typically <userData> in packaged, <project>/data in dev). Critical for
   *  Windows installs to C:\Program Files\Sage which is system-protected. */
  sageUserDataDir: string;
  /** Injected for tests so we can stage "file exists" / "file missing" */
  existsSyncFn?: (path: string) => boolean;
  /** Backend port — main.ts owns this constant so this module stays framework-free */
  port: number;
  /** Optional packaged paths used by callers building provenance diagnostics. */
  appPath?: string;
  userDataPath?: string;
}

export interface DoctorLaunchPlan {
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
  reason:
    | 'dev-conda'
    | 'dev-conda-overridden'
    | 'packaged-win32-bundled'
    | 'packaged-linux-bundled';
}

export type BackendLaunchPlan =
  | {
      kind: 'spawn';
      command: string;
      cmd: string;
      args: string[];
      cwd: string;
      env: Record<string, string>;
      extraEnv: Record<string, string>;
      reason:
        | 'dev-conda'
        | 'dev-conda-overridden'
        | 'packaged-win32-bundled'
        | 'packaged-linux-bundled';
    }
  | {
      kind: 'broken-installer';
      title: string;
      detail: string;
      reason:
        | 'packaged-win32-missing-python'
        | 'packaged-linux-missing-python'
        | 'packaged-macos-unsupported'
        | 'packaged-unknown-platform'
        | 'packaged-no-resources-path';
    };

const PYTHONPATH_SEP_WIN = ';';
const PYTHONPATH_SEP_UNIX = ':';

/**
 * Resolve the absolute path of the python interpreter inside an activated
 * conda env given the env's prefix directory. Used by the dev branch to
 * bypass the ``conda run -n`` wrapper script (see the call site for the
 * pid-mismatch rationale). Behaviour mirrors what ``conda run`` would
 * do for a normal user: unix envs expose ``bin/python``; Windows envs
 * expose ``python.exe`` directly under the prefix.
 *
 * Uses string concatenation rather than ``path.join`` so the result
 * preserves the input separator — conda on Windows reports
 * ``CONDA_PREFIX`` as a backslash path (``C:\…``) and on linux as a
 * forward-slash path (``/opt/…``); mixing in the host's path.sep would
 * silently produce a wrong path when the host platform differs from
 * the env's platform (e.g. tests simulating win32 on a posix runner).
 */
function condaEnvPythonPath(condaPrefix: string, platform: NodeJS.Platform): string {
  return platform === 'win32'
    ? `${condaPrefix}\\python.exe`
    : `${condaPrefix}/bin/python`;
}

/**
 * Pick which Python process to launch.
 *
 * Pure function: takes a snapshot of the runtime (`env`, `resourcesPath`,
 * etc.) + an injectable `existsSyncFn` so tests can deterministically stage
 * "bundled Python present" / "bundled Python missing" without touching disk.
 */
export function resolveBackendLaunchCommand(opts: ResolveOpts): BackendLaunchPlan {
  const existsSyncFn = opts.existsSyncFn ?? defaultExistsSync;
  const sep = opts.platform === 'win32' ? PYTHONPATH_SEP_WIN : PYTHONPATH_SEP_UNIX;

  // ───── Dev branch (isPackaged=false): conda ────────────────────────────
  if (!opts.isPackaged) {
    // SAGE_PYTHON distinguishes two dev intent:
    //   - unset → conda run -n sage-backend python -m backend.main
    //     (current standard "spin up the conda env" workflow)
    //   - set   → use that path as a raw Python interpreter that ALREADY has
    //     `backend` and `sage_core` on its path (e.g. a developer running
    //     `pip install -e` into a system Python). Args become `-m backend.main`
    //     (the same entry as dev-conda), so the `__main__` block runs and
    //     setup_logging() is wired up in every launch mode.
    //
    // The previous implementation paired SAGE_PYTHON's value with conda-flavoured
    // args (`['run', '-n', 'sage-backend', 'python', '-m', 'backend.main']`),
    // which produced broken spawns like `python3 run -n sage-backend ...` when
    // SAGE_PYTHON=python3 (python3 has no `run` subcommand). PR #130 review
    // flagged this — see issue #6.
    const sagePythonOverride = opts.env.SAGE_PYTHON;
    if (sagePythonOverride !== undefined) {
      return {
        kind: 'spawn',
        command: sagePythonOverride,
        cmd: sagePythonOverride,
        args: ['-m', 'backend.main'],
        cwd: process.cwd(),
        env: {
          SAGE_DB_PATH: opts.sageDbPath,
          SAGE_USER_DATA_DIR: opts.sageUserDataDir,
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        extraEnv: {
          SAGE_DB_PATH: opts.sageDbPath,
          SAGE_USER_DATA_DIR: opts.sageUserDataDir,
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        reason: 'dev-conda-overridden',
      };
    }
    // 2026-09-03: prefer the resolved conda env's python binary directly
    // over `conda run -n sage-backend python -m backend.main`. The
    // `conda run` wrapper script produces a 3-deep process tree
    // (conda → bash → python), so ``child_process.spawn``'s ``proc.pid``
    // is the conda wrapper PID, not the python PID. The backend's
    // ``/health/proof`` reports ``os.getpid()`` (the python PID), so
    // Electron's ``waitForBackend`` ``ownsBackend`` check
    // (``health.pid === ownership.pid``) fails and the supervisor
    // times out 90s later with a misleading "后端服务在 30 秒内未响应"
    // dialog — even though the backend was healthy the whole time.
    // Invoking the env's python binary directly gives ``proc.pid`` =
    // the python PID and the check passes. CI sandboxes and power devs
    // who start Electron outside a conda env (no ``CONDA_PREFIX``)
    // still fall through to the ``conda run -n`` path below.
    const condaPrefix = opts.env.CONDA_PREFIX;
    if (condaPrefix) {
      const pythonBin = condaEnvPythonPath(condaPrefix, opts.platform);
      if (existsSyncFn(pythonBin)) {
        return {
          kind: 'spawn',
          command: pythonBin,
          cmd: pythonBin,
          args: ['-m', 'backend.main'],
          cwd: process.cwd(),
          env: {
            SAGE_DB_PATH: opts.sageDbPath,
            SAGE_USER_DATA_DIR: opts.sageUserDataDir,
            PYTHON_BACKEND_PORT: String(opts.port),
          },
          extraEnv: {
            SAGE_DB_PATH: opts.sageDbPath,
            SAGE_USER_DATA_DIR: opts.sageUserDataDir,
            PYTHON_BACKEND_PORT: String(opts.port),
          },
          reason: 'dev-conda',
        };
      }
    }
    return {
      kind: 'spawn',
      command: 'conda',
      cmd: 'conda',
      args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'],
      cwd: process.cwd(),
      env: { SAGE_DB_PATH: opts.sageDbPath, SAGE_USER_DATA_DIR: opts.sageUserDataDir },
      extraEnv: { SAGE_DB_PATH: opts.sageDbPath, SAGE_USER_DATA_DIR: opts.sageUserDataDir },
      reason: 'dev-conda',
    };
  }

  // ───── Packaged branch: must use bundled Python, never conda ───────────
  if (!opts.resourcesPath) {
    return {
      kind: 'broken-installer',
      title: 'Sage 安装包内部状态异常',
      detail:
        'Sage 在 packaged 模式下启动,但 electron 未提供 resourcesPath。\n\n' +
        '这通常意味着安装不完整。请重新下载并安装 Sage:\n' +
        'https://github.com/oneMuggle/sage/releases',
      reason: 'packaged-no-resources-path',
    };
  }

  // Packaged Win32
  if (opts.platform === 'win32') {
    const pyExe = join(opts.resourcesPath, 'python', 'python.exe');
    if (existsSyncFn(pyExe)) {
      return {
        kind: 'spawn',
        command: pyExe,
        cmd: pyExe,
        args: ['-m', 'backend.main'],
        cwd: opts.resourcesPath,
        env: {
          ...packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        extraEnv: {
          ...packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        reason: 'packaged-win32-bundled',
      };
    }
    return {
      kind: 'broken-installer',
      title: 'Python 后端未找到 (安装包可能损坏)',
      detail:
        `已安装 Sage,但 bundled Python 缺失:\n  ${pyExe}\n\n` +
        '这通常意味着 installer 没有正确打包 Python 运行时。\n' +
        '请重新下载并安装 Sage:\n' +
        'https://github.com/oneMuggle/sage/releases',
      reason: 'packaged-win32-missing-python',
    };
  }

  // Packaged Linux
  if (opts.platform === 'linux') {
    const pyBin = join(opts.resourcesPath, 'python', 'bin', 'python3');
    if (existsSyncFn(pyBin)) {
      return {
        kind: 'spawn',
        command: pyBin,
        cmd: pyBin,
        args: ['-m', 'backend.main'],
        cwd: opts.resourcesPath,
        env: {
          ...packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        extraEnv: {
          ...packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
          PYTHON_BACKEND_PORT: String(opts.port),
        },
        reason: 'packaged-linux-bundled',
      };
    }
    return {
      kind: 'broken-installer',
      title: 'Python 后端未找到 (安装包可能损坏)',
      detail:
        `已安装 Sage,但 bundled Python 缺失:\n  ${pyBin}\n\n` +
        '请重新下载并安装 Sage:\n' +
        'https://github.com/oneMuggle/sage/releases',
      reason: 'packaged-linux-missing-python',
    };
  }

  // Packaged macOS
  if (opts.platform === 'darwin') {
    return {
      kind: 'broken-installer',
      title: 'macOS 版尚未发布',
      detail:
        'Sage macOS 版尚未发布 (electron-builder.yml mac.target: null)。\n\n' +
        '请使用 Windows / Linux 版,或自行从源码运行:\n' +
        '  git clone https://github.com/oneMuggle/sage\n' +
        '  conda create -n sage-backend python=3.11 -y\n' +
        '  conda activate sage-backend && pip install -r backend/requirements.txt\n' +
        '  python -m backend.main',
      reason: 'packaged-macos-unsupported',
    };
  }

  // Packaged other (FreeBSD, etc.)
  return {
    kind: 'broken-installer',
    title: `Sage 不支持该平台: ${opts.platform}`,
    detail: '请使用 Windows、Linux,或自行从源码运行 (见 README)。',
    reason: 'packaged-unknown-platform',
  };
}

function packagedEnv(
  resourcesPath: string,
  sageDbPath: string,
  sageUserDataDir: string,
  sep: string,
): Record<string, string> {
  return {
    SAGE_DB_PATH: sageDbPath,
    SAGE_USER_DATA_DIR: sageUserDataDir,
    SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL ?? 'info',
    PYTHONPATH: [join(resourcesPath, 'backend'), join(resourcesPath, 'sage-core')].join(sep),
  };
}

/**
 * Resolve the launch command for the pre-launch ``python -m backend.cli.doctor
 * --json`` subprocess, derived from the supervisor plan returned by
 * ``resolveBackendLaunchCommand``.
 *
 * Design (alpha.12-win7):
 *   - Forks the supervisor plan and replaces the trailing ``-m backend.main``
 *     with ``-m backend.cli.doctor --json``. Conda- and packaged-launched
 *     Python both consume ``-m <module>`` identically, so the swap is safe
 *     across all four spawn reasons (dev-conda, dev-conda-overridden,
 *     packaged-win32-bundled, packaged-linux-bundled).
 *   - Merges ``plan.env + plan.extraEnv`` so the doctor subprocess sees the
 *     same SAGE_DB_PATH / SAGE_USER_DATA_DIR / PYTHON_BACKEND_PORT the
 *     backend supervisor will set on the real spawn. Without the merge the
 *     doctor would probe against host defaults and miss the user-data-dir /
 *     port / db-path the production backend uses.
 *   - Returns ``undefined`` for broken-installer (caller falls back to a
 *     bare ``python`` invocation so doctor remains fail-open in CI).
 *
 * Critical regression (alpha.11-win7):
 *   Previously main.ts passed ``pythonBin=supervisorPlan.command`` and
 *   ``args=supervisorPlan.args`` (which is ``["-m", "backend.main"]`` in
 *   packaged-win32 mode) to ``runDoctorCheck``. ``doctor.ts`` then spawned
 *   ``python.exe -m backend.main`` — i.e. a full uvicorn server — instead
 *   of the doctor CLI. SIGTERM at the 5s timeout didn't propagate to the
 *   orphaned uvicorn child, which kept listening on 8765 and blocked
 *   subsequent ``spawnBackend()`` from binding the port, leaving the
 *   desktop stuck in the "30s 无响应" loop.
 */
export function resolveDoctorLaunchCommand(opts: ResolveOpts): DoctorLaunchPlan | undefined {
  const plan = resolveBackendLaunchCommand(opts);
  if (plan.kind === 'broken-installer') return undefined;

  // Swap the trailing `-m backend.main` for the doctor entry. All four
  // spawn reasons end with `-m backend.main`; replacing the last token
  // preserves any conda/argv prefix verbatim.
  const args = [...plan.args];
  const mainIdx = args.lastIndexOf('backend.main');
  if (mainIdx >= 0) {
    args.splice(mainIdx, 1, 'backend.cli.doctor', '--json');
  } else {
    // Defensive: if for any reason the parent plan doesn't end with
    // `-m backend.main` (future refactor), append the doctor entry so
    // we still produce a runnable command rather than spawning the
    // backend by mistake.
    args.push('-m', 'backend.cli.doctor', '--json');
  }

  // Merge supervisor env so the doctor subprocess probes the exact
  // context the real backend will see.
  const env: Record<string, string> = { ...plan.env, ...plan.extraEnv };

  return {
    command: plan.command,
    args,
    cwd: plan.cwd,
    env,
    reason: plan.reason,
  };
}
