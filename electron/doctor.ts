/**
 * Sage doctor — pre-launch self-check invoked from Electron main process.
 *
 * Spawns `python -m backend.cli.doctor --json` with a hard timeout so the
 * startup path stays snappy. Returns a structured summary that the caller
 * (main.ts) writes to the NDJSON startup log — it is intentionally NOT a
 * blocking gate: doctor is fail-open. Set SAGE_DOCTOR_ON_START=false to
 * skip (used by CI / lightweight smoke paths).
 *
 * Phase 4 (2026-08-07): see docs/plans/2026-08-07_sage-doctor.md §3.
 *
 * Win7 LTS (Py3.8) compat: doctor.py uses ``from __future__ import annotations``
 * and the JSON output schema is identical between Py3.8 and Py3.11, so we
 * don't branch on Python version here — the same caller code works on both
 * branches.
 */

import { spawn } from 'node:child_process';

export type DoctorStatus = 'ok' | 'warn' | 'critical' | 'timeout' | 'error';

export interface DoctorCheck {
  name: string;
  severity: string;
  message: string;
  fix_hint?: string | null;
}

export interface DoctorSummary {
  status: DoctorStatus;
  summary?: { critical: number; warn: number; info: number };
  checks?: DoctorCheck[];
  /** Raw stdout (best-effort, e.g. when JSON.parse failed or output was --text). */
  raw?: string;
  /** Captured stderr from the doctor subprocess. */
  stderr?: string;
  /** Subprocess exit code (null if killed by timeout, undefined if spawn never produced one). */
  exitCode?: number | null;
  /** Wall-clock duration of the run, in milliseconds. */
  elapsed_ms: number;
}

const DEFAULT_TIMEOUT_MS = 5000;

interface ParsedDoctorOutput {
  summary?: DoctorSummary['summary'];
  checks?: DoctorCheck[];
}

function parseJsonOutput(stdout: string): ParsedDoctorOutput | undefined {
  try {
    const parsed: unknown = JSON.parse(stdout);
    if (typeof parsed !== 'object' || parsed === null) return undefined;
    const obj = parsed as Record<string, unknown>;
    const summary =
      obj.summary && typeof obj.summary === 'object'
        ? (obj.summary as DoctorSummary['summary'])
        : undefined;
    const checks = Array.isArray(obj.checks) ? (obj.checks as DoctorCheck[]) : undefined;
    return { summary, checks };
  } catch {
    return undefined;
  }
}

/**
 * Run ``python -m backend.cli.doctor --json`` and return a structured summary.
 *
 * The subprocess always runs with ``--json`` so we get a deterministic
 * payload; if JSON parsing fails we still return ``raw`` for the caller to
 * surface in logs. The 5s default cap is generous: a healthy doctor run
 * completes in <200ms, so the timeout only kicks in on broken-installers.
 *
 * Never throws — all failure modes (spawn error, timeout, non-zero exit,
 * unparseable output) collapse into a structured status field on the
 * returned summary.
 */
export async function runDoctorCheck(
  pythonBin: string,
  projectRoot: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<DoctorSummary> {
  const startedAt = Date.now();
  const proc = spawn(pythonBin, ['-m', 'backend.cli.doctor', '--json'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  let stdout = '';
  let stderr = '';
  proc.stdout?.on('data', (b: Buffer) => {
    stdout += b.toString('utf-8');
  });
  proc.stderr?.on('data', (b: Buffer) => {
    stderr += b.toString('utf-8');
  });

  // Ensure we always detach listeners + kill the child, even if the consumer
  // never awaits this Promise (defensive — main.ts does await, but the
  // process tree should clean up regardless on Electron quit).
  const killTimer = setTimeout(() => {
    try {
      proc.kill('SIGTERM');
    } catch {
      /* ignore — process may already be gone */
    }
    // Escalate to SIGKILL after a short grace period to avoid orphaned
    // python processes on Win7 where SIGTERM can be ignored.
    setTimeout(() => {
      try {
        proc.kill('SIGKILL');
      } catch {
        /* ignore */
      }
    }, 500).unref();
  }, timeoutMs);
  killTimer.unref();

  return new Promise<DoctorSummary>((resolve) => {
    proc.on('error', (err: Error) => {
      clearTimeout(killTimer);
      resolve({
        status: 'error',
        stderr: stderr || err.message,
        exitCode: null,
        elapsed_ms: Date.now() - startedAt,
      });
    });

    proc.on('close', (code: number | null) => {
      clearTimeout(killTimer);
      const elapsed = Date.now() - startedAt;

      // Timeout case: timeoutMs reached, SIGTERM was sent, and the process
      // exited without producing its normal payload (we treat any non-graceful
      // exit after the timer as a timeout regardless of code).
      if (elapsed >= timeoutMs && (stdout === '' || !parseJsonOutput(stdout))) {
        resolve({
          status: 'timeout',
          stderr,
          raw: stdout,
          exitCode: code,
          elapsed_ms: elapsed,
        });
        return;
      }

      const parsed = parseJsonOutput(stdout);
      if (parsed === undefined) {
        // Subprocess exited but stdout wasn't valid JSON (e.g. --text mode,
        // or doctor crashed mid-print). Surface raw so logs are diagnosable.
        resolve({
          status: 'error',
          raw: stdout,
          stderr,
          exitCode: code,
          elapsed_ms: elapsed,
        });
        return;
      }

      // Map Python exit code (0/1/2) onto DoctorStatus.
      // 0 = all OK/INFO, 1 = at least one WARN, 2 = at least one CRITICAL.
      // SIGTERM-aborted runs land in the timeout branch above; any other
      // non-zero is treated as 'error' (e.g. unhandled exception → code 1
      // without going through the WARN-path).
      let status: DoctorStatus;
      if (code === 0) status = 'ok';
      else if (code === 1) status = 'warn';
      else if (code === 2) status = 'critical';
      else status = 'error';

      resolve({
        status,
        summary: parsed.summary,
        checks: parsed.checks,
        stderr: stderr || undefined,
        exitCode: code,
        elapsed_ms: elapsed,
      });
    });
  });
}
