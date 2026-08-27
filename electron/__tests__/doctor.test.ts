// electron/__tests__/doctor.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { EventEmitter } from 'node:events';
import type { Readable } from 'node:stream';

/**
 * alpha.8 (2026-08-27) regression: doctor must accept the supervisor's
 * BackendLaunchPlan rather than hardcoding `-m backend.cli.doctor --json`.
 *
 * Root causes being locked in by these tests:
 * 1. ``runDoctorCheck`` previously hardcoded ``['-m', 'backend.cli.doctor',
 *    '--json']`` and spawned only that argv, so dev-conda ``conda run -n
 *    sage-backend python -m backend.main`` would have produced the illegal
 *    ``conda -m backend.cli.doctor --json``.
 * 2. ``runDoctorCheck`` previously did
 *    ``env: { ...process.env, ...options.env, PYTHONPATH: options.packageRoot }``
 *    which unconditionally overrode any packaged ``PYTHONPATH`` the launcher
 *    set up (resources/backend + resources/sage-core) — breaking ``import
 *    backend.main`` probes inside the packaged env.
 *
 * After the fix, ``runDoctorCheck`` accepts ``args?: string[]`` and
 * ``PYTHONPATH`` is preserved when ``options.env.PYTHONPATH`` is already set.
 */

// Mock node:child_process BEFORE importing the module under test so that
// `import { spawn } from 'node:child_process'` picks up the stub.
type SpawnCall = {
  command: string;
  args: readonly string[];
  options: { cwd?: string; env?: NodeJS.ProcessEnv; stdio?: readonly [string, string, string] };
};

const spawnCalls: SpawnCall[] = [];
let nextStdout = '';
let nextStderr = '';
let nextExitCode: number | null = 0;

function makeFakeProc() {
  const proc = new EventEmitter() as EventEmitter & {
    stdout: Readable;
    stderr: Readable;
    kill: (signal?: string) => boolean;
  };
  const stdoutEE = new EventEmitter();
  const stderrEE = new EventEmitter();
  proc.stdout = stdoutEE as unknown as Readable;
  proc.stderr = stderrEE as unknown as Readable;
  proc.kill = () => true;
  // Emit close asynchronously after listeners attach, mirroring real spawn.
  queueMicrotask(() => {
    if (nextStdout) stdoutEE.emit('data', Buffer.from(nextStdout, 'utf8'));
    if (nextStderr) stderrEE.emit('data', Buffer.from(nextStderr, 'utf8'));
    proc.emit('close', nextExitCode);
  });
  return proc;
}

vi.mock('node:child_process', () => ({
  default: {
    spawn: (command: string, args: readonly string[], options: Record<string, unknown>) => {
      spawnCalls.push({
        command,
        args,
        options: options as SpawnCall['options'],
      });
      return makeFakeProc();
    },
  },
  spawn: (command: string, args: readonly string[], options: Record<string, unknown>) => {
    spawnCalls.push({
      command,
      args,
      options: options as SpawnCall['options'],
    });
    return makeFakeProc();
  },
}));

import { runDoctorCheck, type DoctorLaunchOptions } from '../doctor';

function defaultOptions(overrides: Partial<DoctorLaunchOptions> = {}): DoctorLaunchOptions {
  return {
    pythonBin: 'python',
    packageRoot: '/mock/package',
    cwd: '/mock/cwd',
    env: {},
    ...overrides,
  };
}

const DOCTOR_JSON_OK = JSON.stringify({
  status: 'ok',
  summary: { critical: 0, warn: 0, info: 3 },
  checks: [],
});

beforeEach(() => {
  spawnCalls.length = 0;
  nextStdout = DOCTOR_JSON_OK;
  nextStderr = '';
  nextExitCode = 0;
});

describe('runDoctorCheck argv contract', () => {
  it('使用 options.args 覆盖默认 argv (取代硬编码 -m backend.cli.doctor --json)', async () => {
    // 模拟 dev-conda launcher plan: 命令 = conda, args 已是 ['run', '-n',
    // 'sage-backend', 'python', '-m', 'backend.cli.doctor', '--json'].
    const planArgs = ['run', '-n', 'sage-backend', 'python', '-m', 'backend.cli.doctor', '--json'];
    await runDoctorCheck({
      pythonBin: 'conda',
      packageRoot: '/mock',
      cwd: '/mock',
      env: {},
      args: planArgs,
    });
    expect(spawnCalls).toHaveLength(1);
    expect(spawnCalls[0].command).toBe('conda');
    expect(spawnCalls[0].args).toEqual(planArgs);
    // 关键不变量: 不再生成非法的 `conda -m ...` argv
    expect(spawnCalls[0].args[0]).not.toBe('-m');
  });

  it('options.args 缺省时使用 ["-m", "backend.cli.doctor", "--json"] (向后兼容)', async () => {
    await runDoctorCheck({
      pythonBin: '/path/to/python',
      packageRoot: '/mock',
      cwd: '/mock',
      env: {},
    });
    expect(spawnCalls[0].command).toBe('/path/to/python');
    expect(spawnCalls[0].args).toEqual(['-m', 'backend.cli.doctor', '--json']);
  });

  it('直接 python 解释器 plan (SAGE_PYTHON=python3) 时 argv 不包含 conda run 子命令', async () => {
    // 模拟 SAGE_PYTHON=python3 的 dev 路径, launcher 给出
    // args: ['-m', 'backend.cli.doctor', '--json'].
    await runDoctorCheck({
      pythonBin: 'python3',
      packageRoot: '/mock',
      cwd: '/mock',
      env: {},
      args: ['-m', 'backend.cli.doctor', '--json'],
    });
    expect(spawnCalls[0].command).toBe('python3');
    expect(spawnCalls[0].args).toEqual(['-m', 'backend.cli.doctor', '--json']);
  });

  it('packaged plan: 命令是 bundled python, args 包含 -m backend.cli.doctor --json', async () => {
    // packaged-win32-bundled / packaged-linux-bundled 共享一个 argv 形状.
    const pyExe = '/resources/python/python.exe';
    await runDoctorCheck({
      pythonBin: pyExe,
      packageRoot: '/resources',
      cwd: '/resources',
      env: { PYTHONPATH: '/resources/backend;/resources/sage-core' },
      args: ['-m', 'backend.cli.doctor', '--json'],
    });
    expect(spawnCalls[0].command).toBe(pyExe);
    expect(spawnCalls[0].args).toEqual(['-m', 'backend.cli.doctor', '--json']);
  });
});

describe('runDoctorCheck PYTHONPATH preservation', () => {
  it('options.env.PYTHONPATH 存在时不被 packageRoot 覆盖 (packaged 后端路径不丢失)', async () => {
    await runDoctorCheck({
      pythonBin: '/resources/python/python.exe',
      packageRoot: '/resources',
      cwd: '/resources',
      env: { PYTHONPATH: '/resources/backend;/resources/sage-core' },
      args: ['-m', 'backend.cli.doctor', '--json'],
    });
    const env = spawnCalls[0].options.env ?? {};
    expect(env.PYTHONPATH).toBe('/resources/backend;/resources/sage-core');
    // 关键不变量: PYTHONPATH 必须是 packaged 路径, 不应被 packageRoot
    // ('/resources') 覆盖成单一目录.
    expect(env.PYTHONPATH).not.toBe('/resources');
  });

  it('options.env.PYTHONPATH 缺省时回退到 options.packageRoot (向后兼容)', async () => {
    await runDoctorCheck({
      pythonBin: 'python',
      packageRoot: '/mock/package',
      cwd: '/mock/cwd',
      env: {},
      args: ['-m', 'backend.cli.doctor', '--json'],
    });
    const env = spawnCalls[0].options.env ?? {};
    expect(env.PYTHONPATH).toBe('/mock/package');
  });

  it('options.env 中其它键 (SAGE_DB_PATH / SAGE_USER_DATA_DIR 等) 也透传给子进程', async () => {
    await runDoctorCheck({
      pythonBin: '/resources/python/python.exe',
      packageRoot: '/resources',
      cwd: '/resources',
      env: {
        PYTHONPATH: '/resources/backend;/resources/sage-core',
        SAGE_DB_PATH: '/mock/sage.db',
        SAGE_USER_DATA_DIR: '/mock/userData',
        PYTHON_BACKEND_PORT: '8765',
      },
      args: ['-m', 'backend.cli.doctor', '--json'],
    });
    const env = spawnCalls[0].options.env ?? {};
    expect(env.SAGE_DB_PATH).toBe('/mock/sage.db');
    expect(env.SAGE_USER_DATA_DIR).toBe('/mock/userData');
    expect(env.PYTHON_BACKEND_PORT).toBe('8765');
  });
});

describe('runDoctorCheck cwd + interface', () => {
  it('使用 options.cwd 而非 options.packageRoot', async () => {
    await runDoctorCheck(defaultOptions({ cwd: '/launcher/cwd', packageRoot: '/something/else' }));
    expect(spawnCalls[0].options.cwd).toBe('/launcher/cwd');
  });

  it('options.cwd 缺省时回退到 options.packageRoot', async () => {
    await runDoctorCheck({ pythonBin: 'python', packageRoot: '/only/package', env: {} });
    expect(spawnCalls[0].options.cwd).toBe('/only/package');
  });

  it('DoctorLaunchOptions 接受 args?: string[] 字段 (TS 类型契约)', () => {
    // 编译期断言: 下面的字面量必须能通过 TS 校验.
    const opts: DoctorLaunchOptions = {
      pythonBin: 'python',
      packageRoot: '/mock',
      args: ['-m', 'backend.cli.doctor', '--json'],
    };
    expect(opts.args).toEqual(['-m', 'backend.cli.doctor', '--json']);
  });
});
