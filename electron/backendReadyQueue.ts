/**
 * Backend readiness queue.
 *
 * PR #2976 made the main window visible before the Python backend is ready
 * (first-frame show instead of wait-for-health). Renderer components fire
 * their one-shot startup IPC (loadSessions, workspace bind/refresh, ...)
 * during that window; the readiness gate in `sage:invoke` /
 * `sage:backend-request` used to reject them with BackendNotReadyError and
 * nothing ever retried, leaving the sidebar session list empty and the
 * office workbench stuck on a "后端服务尚未就绪" banner.
 *
 * Fix: while the backend lifecycle is `idle` or `starting`, IPC requests
 * are parked here instead of failing. The main process flushes the queue
 * once lifecycle flips to `ready`; only terminal states (app quitting,
 * auto-restart attempts exhausted) reject the parked requests.
 *
 * Pure module — no Electron imports — so the semantics are unit-testable
 * without spinning up the runtime.
 */
import { BackendNotReadyError } from './invoke';

export interface BackendReadyQueueLogger {
  warn: (message: string, meta?: unknown) => void;
}

export interface BackendReadyQueueOptions {
  /** Upper bound on parked tasks. Beyond it new enqueues fail fast. */
  maxSize?: number;
  /** Invoked when an enqueue is rejected because the queue is full. */
  onOverflow?: (label: string) => void;
  logger?: BackendReadyQueueLogger;
}

export interface BackendReadyQueue {
  /**
   * Park `task` until `flush()` (backend ready) or `rejectAll()` (terminal
   * state). Returns the task's own result once it finally runs.
   */
  enqueue<T>(task: () => Promise<T>, label: string): Promise<T>;
  /** Run every parked task in FIFO order. Idempotent — drains atomically. */
  flush(): void;
  /** Reject every parked task with `reason` and never run them. */
  rejectAll(reason: Error): void;
  /** Number of tasks currently parked. */
  size(): number;
}

const DEFAULT_MAX_SIZE = 200;

interface QueuedEntry {
  label: string;
  run: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
}

export function createBackendReadyQueue(options: BackendReadyQueueOptions = {}): BackendReadyQueue {
  const maxSize = options.maxSize ?? DEFAULT_MAX_SIZE;
  let pending: QueuedEntry[] = [];

  const overflowError = () =>
    new BackendNotReadyError('后端服务尚未就绪,请求队列已满,请稍候或重启 Sage');

  return {
    enqueue<T>(task: () => Promise<T>, label: string): Promise<T> {
      if (pending.length >= maxSize) {
        options.logger?.warn('backend-ready-queue: overflow, rejecting request', {
          label,
          size: pending.length,
        });
        options.onOverflow?.(label);
        return Promise.reject(overflowError());
      }
      return new Promise<T>((resolve, reject) => {
        pending.push({
          label,
          run: task as () => Promise<unknown>,
          resolve: resolve as (value: unknown) => void,
          reject,
        });
      });
    },

    flush(): void {
      if (pending.length === 0) return;
      // Drain atomically so a re-entrant flush (double `backend:ready`)
      // cannot run the same entries twice.
      const batch = pending;
      pending = [];
      for (const entry of batch) {
        // Start in FIFO order, but let them overlap — this matches the
        // pre-regression behavior where each invoke ran as soon as the
        // backend was ready. One slow task must not block the rest.
        void entry.run().then(entry.resolve, (err) => {
          options.logger?.warn('backend-ready-queue: flushed task failed', {
            label: entry.label,
            err: err instanceof Error ? err.message : String(err),
          });
          entry.reject(err);
        });
      }
    },

    rejectAll(reason: Error): void {
      if (pending.length === 0) return;
      const batch = pending;
      pending = [];
      for (const entry of batch) {
        entry.reject(reason);
      }
    },

    size(): number {
      return pending.length;
    },
  };
}
