/**
 * Background-task aggregation for the pet.
 *
 * The Task Center lives in the renderer (office/wiki/custom/orchestration
 * tasks are registered there), so the main process receives a sanitized
 * report and only uses it when no chat session is active.
 */

import type {
  PetAction,
  PetBubbleKey,
  PetBubbleKind,
  PetDetail,
  PetSnapshot,
  PetTaskReport,
  PetTaskStatus,
} from './types';

const STATUSES = new Set<PetTaskStatus>([
  'queued',
  'running',
  'awaiting_approval',
  'paused',
  'succeeded',
  'failed',
  'cancelled',
]);

const FAILED_TASK_WINDOW_MS = 10 * 60_000;
const PRIORITY: Record<PetTaskStatus, number> = {
  awaiting_approval: 100,
  failed: 90,
  running: 60,
  queued: 50,
  paused: 40,
  succeeded: 0,
  cancelled: 0,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function normalizeTaskReports(input: unknown, limit = 20): PetTaskReport[] {
  if (!Array.isArray(input)) return [];
  const seen = new Set<string>();
  const result: PetTaskReport[] = [];
  for (const raw of input) {
    if (!isRecord(raw)) continue;
    const id = text(raw.id, 128);
    const title = text(raw.title, 200);
    const status = typeof raw.status === 'string' ? (raw.status as PetTaskStatus) : null;
    if (!id || !title || !status || !STATUSES.has(status) || seen.has(id)) continue;
    seen.add(id);
    const percent = finiteNumber(raw.percent);
    result.push({
      id,
      kind: text(raw.kind, 32) ?? 'custom',
      title,
      status,
      phase: text(raw.phase, 120),
      percent: percent === null ? null : Math.min(100, Math.max(0, Math.round(percent))),
      sessionId: text(raw.sessionId, 128),
      runId: text(raw.runId, 128),
      error: text(raw.error, 240),
      startedAt: finiteNumber(raw.startedAt),
      finishedAt: finiteNumber(raw.finishedAt),
    });
    if (result.length >= limit) break;
  }
  return result;
}

/**
 * Combine Task Center reports (renderer registered) with polled background
 * sources (orchestration/scheduled). Primary entries win duplicate ids.
 */
export function mergeTaskReports(
  primary: readonly PetTaskReport[],
  secondary: readonly PetTaskReport[],
  limit = 20,
): PetTaskReport[] {
  const seen = new Set<string>();
  const merged: PetTaskReport[] = [];
  for (const task of [...primary, ...secondary]) {
    if (seen.has(task.id)) continue;
    seen.add(task.id);
    merged.push(task);
    if (merged.length >= limit) break;
  }
  return merged;
}

interface TaskAction {
  action: PetAction;
  detail: PetDetail | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
}

function actionFor(status: PetTaskStatus): TaskAction | null {
  switch (status) {
    case 'awaiting_approval':
      return { action: 'waiting', detail: null, bubbleKey: 'waiting', bubbleKind: 'waiting' };
    case 'failed':
      return { action: 'error', detail: null, bubbleKey: 'error', bubbleKind: 'error' };
    case 'running':
    case 'queued':
    case 'paused':
      return { action: 'acting', detail: 'other', bubbleKey: 'tool_other', bubbleKind: 'info' };
    default:
      return null;
  }
}

/**
 * Only override an idle/sleeping pet: an active chat session always wins.
 * Failed tasks are shown for a bounded window so they do not dominate forever.
 */
export function applyTaskOverrides(
  snapshot: PetSnapshot,
  tasks: PetTaskReport[],
  now: number,
): PetSnapshot {
  if (snapshot.action !== 'idle' && snapshot.action !== 'sleeping') return snapshot;
  const candidates = tasks.filter((task) => {
    if (task.status === 'failed') {
      return task.finishedAt !== null && task.finishedAt !== undefined
        ? task.finishedAt >= now - FAILED_TASK_WINDOW_MS
        : false;
    }
    return (
      task.status === 'awaiting_approval' ||
      task.status === 'running' ||
      task.status === 'queued' ||
      task.status === 'paused'
    );
  });
  if (candidates.length === 0) return snapshot;
  const best = [...candidates].sort(
    (a, b) => PRIORITY[b.status] - PRIORITY[a.status] || (b.startedAt ?? 0) - (a.startedAt ?? 0),
  )[0];
  const mapped = actionFor(best.status);
  if (!mapped) return snapshot;
  return {
    ...snapshot,
    ...mapped,
    sessionId: best.sessionId ?? snapshot.sessionId,
    sessionTitle: best.title,
    toolName: '后台任务',
  };
}
