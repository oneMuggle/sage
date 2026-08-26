/**
 * Doctor self-check unit tests (2026-08-26).
 *
 * Lock down the spawn contract so the next refactor can't reintroduce:
 *   - hard-coded `['-m', 'backend.cli.doctor', '--json']` argv that
 *     breaks conda/--json layering (the original bug produced
 *     `conda -m backend.cli.doctor --json`)
 *   - PYTHONPATH forced to `packageRoot`, which clobbered the packaged
 *     supervisor's `resourcesPath/backend:resourcesPath/sage-core`
 *   - missing cwd / missing env propagation
 *
 * Strategy: replace `node:child_process.spawn` with a mock that records
 * (cmd, args, options) tuples. Tests assert what `runDoctorCheck` actually
 * passed to spawn — without spinning up a real Python subprocess.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { spawnCalls } = vi.hoisted(() => ({
  spawnCalls: [] as Array<{
    cmd: string;
    args: readonly string[];
    options: Record<string, unknown>;
  }>,
}));

vi.mock('node:child_process', () => {
  type Handler = (...args: unknown[]) => void;
  // Per-spawn handler registry so `on('close', cb)` registrations from
  // doctor.ts can be triggered synchronously via microtask. Tests don't
  // care about subprocess output — they only assert on the spawn() call
  // arguments — so firing close(0) right away keeps `await runDoctorCheck`
  // from hanging while still recording the spawn tuple.
  const handlers = new Map<string, Handler[]>();
  const fakeChild = {
    stdout: { on: () => undefined },
    stderr: { on: () => undefined },
    on: (event: string, cb: Handler) => {
      const arr = handlers.get(event) ?? [];
      arr.push(cb);
      handlers.set(event, arr);
    },
    once: (event: string, cb: Handler) => {
      const arr = handlers.get(event) ?? [];
      arr.push(cb);
      handlers.set(event, arr);
    },
    kill: () => true,
  };
  const spawnFn = ((...args: unknown[]) => {
    const [cmd, argv, options] = args as [string, readonly string[], Record<string, unknown>];
    spawnCalls.push({ cmd, args: argv, options });
    // Emit close on next microtask so the doctor.ts promise resolves
    // quickly. Microtasks run under fake timers (they aren't timer-driven),
    // so `await runDoctorCheck(...)` won't hang on the test's 5s timeout.
    queueMicrotask(() => {
      for (const cb of handlers.get('close') ?? []) cb(0);
    });
    return fakeChild;
  }) as unknown as typeof import('node:child_process').spawn;
  return {
    spawn: spawnFn,
    // node:child_process exposes both named and a CommonJS default; some
    // interop paths reach for `default`. Provide a stub for those.
    default: { spawn: spawnFn },
  };
});

import { runDoctorCheck } from '../doctor';

function lastSpawn(): {
  cmd: string;
  args: readonly string[];
  options: Record<string, unknown>;
} {
  const call = spawnCalls[spawnCalls.length - 1];
  if (!call) throw new Error('spawn was not called');
  return call;
}

describe('runDoctorCheck (2026-08-26 argv + env contract)', () => {
  beforeEach(() => {
    spawnCalls.length = 0;
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('spawns `python -m backend.cli.doctor --json` for legacy pythonBin string fallback', async () => {
    // Backward-compat path: callers that still pass `pythonBin` get the
    // historical default argv. Used when the supervisor can't produce a
    // spawn plan (broken-installer → fallback to bare python).
    vi.useFakeTimers();
    const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
    const captured = lastSpawn();
    expect(captured.cmd).toBe('python');
    expect(captured.args).toEqual(['-m', 'backend.cli.doctor', '--json']);
    expect(captured.options.cwd).toBe('/mock/project');
    await vi.advanceTimersByTimeAsync(6_000);
    await promise;
  });

  it('spawns the FULL argv when caller supplies it (no hard-coded --json)', async () => {
    // Regression guard: doctor.ts used to hard-code
    // `['-m', 'backend.cli.doctor', '--json']` regardless of options.args.
    // That broke the dev-conda branch (passed command='conda', ignored
    // the supervisor's `['run', '-n', 'sage-backend', 'python',
    // '-m', 'backend.main']` argv).
    vi.useFakeTimers();
    const promise = runDoctorCheck({
      pythonBin: 'conda',
      args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.cli.doctor', '--json'],
      cwd: '/mock/project',
      env: { SAGE_DB_PATH: '/mock/sage.db' },
      packageRoot: '/mock/project',
    } as unknown as Parameters<typeof runDoctorCheck>[0]).catch(() => undefined);
    const captured = lastSpawn();
    expect(captured.cmd).toBe('conda');
    expect(captured.args).toEqual([
      'run',
      '-n',
      'sage-backend',
      'python',
      '-m',
      'backend.cli.doctor',
      '--json',
    ]);
    expect(captured.options.cwd).toBe('/mock/project');
    await vi.advanceTimersByTimeAsync(6_000);
    await promise;
  });

  it('does NOT overwrite PYTHONPATH when env already supplies one', async () => {
    // Packaged supervisor sets PYTHONPATH to
    // `<resources>/backend:<resources>/sage-core`. Old doctor.ts forced
    // `PYTHONPATH: options.packageRoot`, replacing it with a single path
    // missing `backend`/`sage-core` — the doctor subprocess crashed on
    // `import backend.cli.doctor`.
    vi.useFakeTimers();
    const promise = runDoctorCheck({
      pythonBin: '/mock/resources/python/bin/python3',
      args: ['-m', 'backend.cli.doctor', '--json'],
      cwd: '/mock/resources',
      env: {
        PYTHONPATH: '/mock/resources/backend:/mock/resources/sage-core',
        SAGE_DB_PATH: '/mock/sage.db',
      },
      packageRoot: '/mock/project',
    } as unknown as Parameters<typeof runDoctorCheck>[0]).catch(() => undefined);
    const captured = lastSpawn();
    const env = captured.options.env as Record<string, string>;
    expect(env.PYTHONPATH).toBe('/mock/resources/backend:/mock/resources/sage-core');
    expect(env.SAGE_DB_PATH).toBe('/mock/sage.db');
    await vi.advanceTimersByTimeAsync(6_000);
    await promise;
  });

  it('falls back to packageRoot for PYTHONPATH when caller did not supply one', async () => {
    // Dev branch: conda handles PYTHONPATH via env name, so doctor should
    // not need to set it. If a dev caller doesn't supply PYTHONPATH, we
    // default to packageRoot — this test locks the choice so it stays
    // intentional, not accidental.
    vi.useFakeTimers();
    const promise = runDoctorCheck({
      pythonBin: 'conda',
      args: ['run', '-n', 'sage-backend', 'python', '-m', 'backend.cli.doctor', '--json'],
      cwd: '/mock/project',
      env: {},
      packageRoot: '/mock/project',
    } as unknown as Parameters<typeof runDoctorCheck>[0]).catch(() => undefined);
    const captured = lastSpawn();
    const env = captured.options.env as Record<string, string>;
    expect(env.PYTHONPATH).toBe('/mock/project');
    await vi.advanceTimersByTimeAsync(6_000);
    await promise;
  });

  it('legacy string signature: PYTHONPATH defaults to projectRoot', async () => {
    // Backward-compat: when caller passes `(pythonBin, projectRoot)`,
    // doctor.ts must default PYTHONPATH to projectRoot. Without this,
    // the legacy CI smoke path would import-fail on bare `python`.
    vi.useFakeTimers();
    const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
    const captured = lastSpawn();
    const env = captured.options.env as Record<string, string>;
    expect(env.PYTHONPATH).toBe('/mock/project');
    await vi.advanceTimersByTimeAsync(6_000);
    await promise;
  });
});
