/**
 * NDJSON client for subscribing to orchestration run events.
 *
 * Connects to `GET /orch/runs/{runId}/events?after_seq={seq}` via Electron IPC relay
 * and yields parsed `RunEvent` objects. Supports reconnection via `after_seq` to resume
 * from the last seen sequence number.
 *
 * Transport: Uses Electron IPC relay (`orch-events-{runId}-seq-{afterSeq}`) which
 * proxies through main process with proper auth headers. Falls back to direct fetch
 * for non-Electron environments (testing/development).
 */

import type { RunEvent } from './orchEvents';

const MAX_EVENT_LINE_BYTES = 256 * 1024;
const MAX_BUFFER_BYTES = 512 * 1024;
const EVENT_TYPES: ReadonlySet<string> = new Set([
  'task.planned',
  'task.queued',
  'task.started',
  'task.waiting_input',
  'task.waiting_approval',
  'task.retrying',
  'task.succeeded',
  'task.completed',
  'task.failed',
  'task.cancel_requested',
  'task.cancelled',
  'task.blocked',
  'task.progress',
  'task.step.created',
  'task.step.started',
  'task.step.completed',
  'task.step.failed',
  'task.step.progress',
  'task.step.output_delta',
  'task.step.waiting',
  'task.context.append_requested',
  'task.context.appended',
  'task.context.delivered',
  'task.context.acknowledged',
  'task.run_requested',
  'task.approval_requested',
  'task.approval_resolved',
  'run.created',
  'run.started',
  'run.completed',
  'run.failed',
  'run.cancelled',
  'run.paused',
  'run.plan.updated',
  'run.queued',
  'run.resumed',
  'run.cancel_requested',
  'run.recovered',
]);

export interface OrchEventStreamOptions {
  /** Run ID to subscribe to */
  runId: string;
  /** Resume from this sequence number (exclusive) */
  afterSeq?: number;
  /** AbortSignal for cancellation */
  signal?: AbortSignal;
  /** Callback for connection errors */
  onError?: (error: Error) => void;
}

/**
 * Subscribe to a run's event stream as an async generator.
 *
 * Usage:
 * ```ts
 * const stream = subscribeOrchEvents({ runId: 'run-123', afterSeq: 42 });
 * for await (const event of stream) {
 *   // event.event_type, event.seq available for processing
 * }
 * ```
 *
 * In Electron: uses IPC relay with auth. In browser: falls back to direct fetch.
 */
export async function* subscribeOrchEvents(
  options: OrchEventStreamOptions,
): AsyncGenerator<RunEvent, void, unknown> {
  const { runId, afterSeq = 0, signal } = options;

  // Electron IPC relay path
  if (typeof window !== 'undefined' && window.electronAPI?.listen) {
    const eventName = afterSeq > 0 ? `orch-events-${runId}-seq-${afterSeq}` : `orch-events-${runId}`;
    const eventQueue: RunEvent[] = [];
    let resolveNext: (() => void) | null = null;
    let done = false;
    const error: Error | null = null;

    const unsubscribe = await window.electronAPI.listen(
      eventName,
      (rawEvent: unknown) => {
        const parsed = parseOrchEventFromIpc(rawEvent);
        if (parsed) {
          eventQueue.push(parsed);
          if (resolveNext) {
            resolveNext();
            resolveNext = null;
          }
        }
      },
    );

    const cleanup = () => {
      done = true;
      if (resolveNext) {
        resolveNext();
        resolveNext = null;
      }
      unsubscribe?.();
    };

    signal?.addEventListener('abort', cleanup, { once: true });

    try {
      while (!done) {
        if (eventQueue.length > 0) {
          yield eventQueue.shift()!;
        } else if (error) {
          throw error;
        } else {
          await new Promise<void>((resolve) => {
            resolveNext = resolve;
          });
        }
      }
    } finally {
      cleanup();
    }
    return;
  }

  // Fallback: direct fetch (for testing outside Electron)
  yield* subscribeOrchEventsDirect(options);
}

/**
 * Direct fetch fallback (non-Electron environments).
 * NOT for production use — bypasses auth. Use only for testing.
 */
async function* subscribeOrchEventsDirect(
  options: OrchEventStreamOptions & { baseUrl?: string },
): AsyncGenerator<RunEvent, void, unknown> {
  const { runId, afterSeq = 0, baseUrl = '', signal, onError } = options;
  const url = `${baseUrl}/api/v1/orch/runs/${encodeURIComponent(runId)}/events?after_seq=${afterSeq}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/x-ndjson' },
      signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      return;
    }
    const error = err instanceof Error ? err : new Error(String(err));
    onError?.(error);
    throw error;
  }

  if (!response.ok) {
    const error = new Error(
      `Failed to subscribe to orch events: ${response.status} ${response.statusText}`,
    );
    onError?.(error);
    throw error;
  }

  if (!response.body) {
    const error = new Error('Response body is null');
    onError?.(error);
    throw error;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // Process any remaining buffer
        if (buffer.trim()) {
          if (new TextEncoder().encode(buffer).byteLength > MAX_EVENT_LINE_BYTES) {
            throw new Error('Orchestration event line exceeded limit');
          }
          const event = parseOrchEventLine(buffer);
          if (event) yield event;
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      if (new TextEncoder().encode(buffer).byteLength > MAX_BUFFER_BYTES) {
        throw new Error('Orchestration event stream buffer exceeded limit');
      }
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (new TextEncoder().encode(line).byteLength > MAX_EVENT_LINE_BYTES) {
          throw new Error('Orchestration event line exceeded limit');
        }
        const event = parseOrchEventLine(line);
        if (event) yield event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parse a single NDJSON line into a RunEvent.
 * Exported for testing.
 */
export function parseOrchEventLine(line: string): RunEvent | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.length > MAX_EVENT_LINE_BYTES) return null;
  try {
    const value: unknown = JSON.parse(trimmed);
    if (!isRunEventEnvelope(value)) return null;
    return value;
  } catch {
    return null;
  }
}

/**
 * Parse an event received via Electron IPC into a RunEvent.
 * IPC events are already parsed JSON objects (not NDJSON strings).
 */
export function parseOrchEventFromIpc(rawEvent: unknown): RunEvent | null {
  if (!isRunEventEnvelope(rawEvent)) return null;
  return rawEvent;
}

function isRunEventEnvelope(value: unknown): value is RunEvent {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  return (
    isBoundedString(event.event_id, 256) &&
    isBoundedString(event.run_id, 256) &&
    isNonNegativeInteger(event.seq) &&
    typeof event.event_type === 'string' &&
    EVENT_TYPES.has(event.event_type) &&
    isNonNegativeInteger(event.occurred_at) &&
    isBoundedString(event.producer, 256) &&
    isNonNegativeInteger(event.producer_generation) &&
    isEntity(event.entity) &&
    isRecord(event.payload) &&
    (event.visibility === 'user' || event.visibility === 'internal') &&
    isBoundedString(event.schema_version, 64)
  );
}

function isEntity(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return Object.values(value).every((item) => item === undefined || isBoundedString(item, 256));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isBoundedString(value: unknown, maxLength: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= maxLength;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
