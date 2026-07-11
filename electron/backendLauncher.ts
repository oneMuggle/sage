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
 *     → conda run -n sage-backend python -m backend.main
 *     → SAGE_PYTHON env can override `conda` to e.g. `python3` for power devs
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
}

export type BackendLaunchPlan =
  | {
      kind: 'spawn';
      cmd: string;
      args: string[];
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
    //     `pip install -e` into a system Python). Args become `-m uvicorn ...`
    //     because there is no conda subcommand namespace to delegate to.
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
        cmd: sagePythonOverride,
        args: [
          '-m',
          'uvicorn',
          'backend.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          String(opts.port),
        ],
        extraEnv: { SAGE_DB_PATH: opts.sageDbPath, SAGE_USER_DATA_DIR: opts.sageUserDataDir },
        reason: 'dev-conda-overridden',
      };
    }
    return {
      kind: 'spawn',
      cmd: 'conda',
      args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.main'],
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
        cmd: pyExe,
        args: [
          '-m',
          'uvicorn',
          'backend.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          String(opts.port),
        ],
        extraEnv: packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
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
        cmd: pyBin,
        args: [
          '-m',
          'uvicorn',
          'backend.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          String(opts.port),
        ],
        extraEnv: packagedEnv(opts.resourcesPath, opts.sageDbPath, opts.sageUserDataDir, sep),
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
    PYTHONPATH: [join(resourcesPath, 'backend'), join(resourcesPath, 'sage-core')].join(sep),
  };
}
