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

const { spawnCalls, killLog } = vi.hoisted(() => ({
  spawnCalls: [] as Array<{
    cmd: string;
    args: readonly string[];
    options: Record<string, unknown>;
  }>,
  killLog: [] as Array<{ signal: string; t: number }>,
}));

vi.mock('node:child_process', () => {
  type Handler = (...args: unknown[]) => void;
  // Per-spawn handler registry so `on('close', cb)` registrations from
  // doctor.ts can be triggered synchronously via microtask. By default we
  // emit close on next microtask so legacy tests can assert on spawn() args
  // without hanging. The env-timeout tests below opt into ``delayClose``
  // mode to let the killTimer fire first; they then call ``__closeSpawn``
  // to manually fire close() once the SIGTERM assertion is done.
  let delayClose = false;
  const handlers = new Map<string, Handler[]>();
  const fakeChild: Record<string, unknown> = {
    stdout: { on: () => undefined },
    stderr: { on: () => undefined },
    kill: (signal?: string) => {
      killLog.push({ signal: signal ?? 'SIGTERM', t: Date.now() });
      return true;
    },
    __closeSpawn: () => {
      for (const cb of handlers.get('close') ?? []) cb(0);
    },
  };
  fakeChild.on = (event: string, cb: Handler) => {
    const arr = handlers.get(event) ?? [];
    arr.push(cb);
    handlers.set(event, arr);
  };
  fakeChild.once = (event: string, cb: Handler) => {
    const arr = handlers.get(event) ?? [];
    arr.push(cb);
    handlers.set(event, arr);
  };
  const spawnFn = ((...args: unknown[]) => {
    const [cmd, argv, options] = args as [string, readonly string[], Record<string, unknown>];
    spawnCalls.push({ cmd, args: argv, options });
    if (delayClose) {
      // Stay "alive" until tests manually call __closeSpawn().
      return fakeChild;
    }
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
    __setDelayClose: (v: boolean) => {
      delayClose = v;
    },
    __closeSpawn: () => (fakeChild.__closeSpawn as () => void)(),
  };
});

import { runDoctorCheck } from '../doctor';
import * as cpMock from 'node:child_process';

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
    await vi.advanceTimersByTimeAsync(21_000);
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
    await vi.advanceTimersByTimeAsync(21_000);
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
    await vi.advanceTimersByTimeAsync(21_000);
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
    await vi.advanceTimersByTimeAsync(21_000);
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
    await vi.advanceTimersByTimeAsync(21_000);
    await promise;
  });

  describe('SAGE_DOCTOR_TIMEOUT_MS env override (2026-09-08)', () => {
    // Alpha13 doctor (with jieba dict + heavy check expansion) takes ~8-10s
    // on packaged Win32 cold start. Default bumped to 20s; CI smoke paths
    // tighten via SAGE_DOCTOR_TIMEOUT_MS to keep their assertions tight.
    //
    // We observe the configured timeout via the SIGTERM kill moment:
    // doctor.ts fires ``proc.kill('SIGTERM')`` exactly ``timeoutMs`` ms
    // after spawn. The mock records each kill into ``killLog`` so we can
    // assert the delta between spawn and kill matches the configured cap.
    const ORIGINAL_ENV = process.env.SAGE_DOCTOR_TIMEOUT_MS;

    beforeEach(() => {
      killLog.length = 0;
      // Suppress the microtask-emitted close() so the spawn stays "alive"
      // and the killTimer actually fires (otherwise close→clearTimeout
      // races us and the SIGTERM never happens).
      (cpMock as unknown as { __setDelayClose: (v: boolean) => void }).__setDelayClose(true);
    });

    afterEach(() => {
      (cpMock as unknown as { __setDelayClose: (v: boolean) => void }).__setDelayClose(false);
      if (ORIGINAL_ENV === undefined) {
        delete process.env.SAGE_DOCTOR_TIMEOUT_MS;
      } else {
        process.env.SAGE_DOCTOR_TIMEOUT_MS = ORIGINAL_ENV;
      }
    });

    it('honours SAGE_DOCTOR_TIMEOUT_MS=3000 (SIGTERM at +3000ms, not +20000ms)', async () => {
      process.env.SAGE_DOCTOR_TIMEOUT_MS = '3000';
      vi.useFakeTimers();
      const startedAt = Date.now();
      const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
      // Advance to exactly the env-configured deadline → killTimer fires SIGTERM.
      await vi.advanceTimersByTimeAsync(3_000);
      // Verify SIGTERM happened at the right wall-clock (this is the
      // behaviour we actually care about; the SIGKILL escalation is just
      // a safety net).
      expect(killLog).toHaveLength(1);
      expect(killLog[0].signal).toBe('SIGTERM');
      expect(killLog[0].t - startedAt).toBeGreaterThanOrEqual(2_990);
      expect(killLog[0].t - startedAt).toBeLessThanOrEqual(3_010);
      // Now advance past the 500ms SIGKILL grace and manually fire close
      // so the promise resolves (in real life, the Python child would
      // exit on SIGKILL; the mock has no such reaction).
      await vi.advanceTimersByTimeAsync(500);
      (cpMock as unknown as { __closeSpawn?: () => void }).__closeSpawn?.();
      await promise;
    });

    it('default 20s fires SIGTERM at ~+20000ms when env unset', async () => {
      delete process.env.SAGE_DOCTOR_TIMEOUT_MS;
      vi.useFakeTimers();
      const startedAt = Date.now();
      const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
      await vi.advanceTimersByTimeAsync(20_000);
      expect(killLog).toHaveLength(1);
      expect(killLog[0].t - startedAt).toBeGreaterThanOrEqual(19_990);
      await vi.advanceTimersByTimeAsync(500);
      (cpMock as unknown as { __closeSpawn?: () => void }).__closeSpawn?.();
      await promise;
    });

    it('falls back to default when env is malformed', async () => {
      process.env.SAGE_DOCTOR_TIMEOUT_MS = 'not-a-number';
      vi.useFakeTimers();
      const startedAt = Date.now();
      const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
      await vi.advanceTimersByTimeAsync(20_000);
      expect(killLog[0].t - startedAt).toBeGreaterThanOrEqual(19_990);
      await vi.advanceTimersByTimeAsync(500);
      (cpMock as unknown as { __closeSpawn?: () => void }).__closeSpawn?.();
      await promise;
    });

    it('treats env=0 as default (does not silently disable the timeout)', async () => {
      // Naive ``Number.parseInt('0')`` = 0 → ``setTimeout(cb, 0)`` fires
      // next tick → effectively no timeout. Guard rejects <= 0 in
      // resolveTimeoutMs so this can't happen.
      process.env.SAGE_DOCTOR_TIMEOUT_MS = '0';
      vi.useFakeTimers();
      const startedAt = Date.now();
      const promise = runDoctorCheck('python', '/mock/project').catch(() => undefined);
      await vi.advanceTimersByTimeAsync(20_000);
      expect(killLog[0].t - startedAt).toBeGreaterThanOrEqual(19_990);
      await vi.advanceTimersByTimeAsync(500);
      (cpMock as unknown as { __closeSpawn?: () => void }).__closeSpawn?.();
      await promise;
    });
  });
});
