/**
 * Multi-session attention (global, untruncated counts) and per-pet follow
 * resolution (which session a single pet portrays).
 *
 * Pure module: no Electron imports, so it is directly unit-testable.
 */

import { FAILED_TASK_WINDOW_MS } from './tasks';
import type { PetSessionState } from './state';
import type { PetAction, PetAttentionSummary, PetFollowMode, PetTaskReport } from './types';

export const ACTION_PRIORITY: Record<PetAction, number> = {
  waiting: 100,
  // Active work outranks a terminal error: one session failing must not hide
  // that another session is still running.
  acting: 60,
  retry: 50,
  thinking: 40,
  observing: 30,
  error: 25,
  done: 20,
  idle: 0,
  sleeping: 0,
};

export const ACTIVE_ACTIONS = new Set<PetAction>([
  'thinking',
  'acting',
  'waiting',
  'retry',
  'observing',
]);

export interface PetFollowOptions {
  mode: PetFollowMode;
  focusSessionId: string | null;
  pinnedSessionId: string | null;
}

function sortedEntries(sessions: PetSessionState): Array<[string, PetSessionState[string]]> {
  return Object.entries(sessions).sort(
    ([, a], [, b]) =>
      ACTION_PRIORITY[b.action] - ACTION_PRIORITY[a.action] || b.updatedAt - a.updatedAt,
  );
}

export function computeAttention(
  sessions: PetSessionState,
  tasks: readonly PetTaskReport[],
  now: number,
): PetAttentionSummary {
  let needsYou = 0;
  let failed = 0;
  let running = 0;
  const waiting: Array<{ sessionId: string; updatedAt: number }> = [];

  for (const [sessionId, session] of Object.entries(sessions)) {
    if (session.action === 'waiting') {
      needsYou += 1;
      waiting.push({ sessionId, updatedAt: session.updatedAt });
    } else if (session.action === 'error') {
      failed += 1;
    } else if (ACTIVE_ACTIONS.has(session.action)) {
      running += 1;
    }
  }

  let activeTasks = 0;
  for (const task of tasks) {
    if (task.status === 'awaiting_approval') {
      needsYou += 1;
      activeTasks += 1;
    } else if (task.status === 'running' || task.status === 'queued' || task.status === 'paused') {
      activeTasks += 1;
    } else if (task.status === 'failed') {
      const finished = task.finishedAt ?? task.startedAt ?? now;
      if (finished >= now - FAILED_TASK_WINDOW_MS) failed += 1;
    }
  }

  waiting.sort((a, b) => b.updatedAt - a.updatedAt);
  return {
    needsYou,
    failed,
    running,
    activeTasks,
    total: needsYou + failed + running + activeTasks,
    needsYouSessionIds: waiting.slice(0, 20).map((entry) => entry.sessionId),
  };
}

/** Live sessions in urgency order (waiting first). */
export function liveSessionIds(sessions: PetSessionState): string[] {
  return sortedEntries(sessions)
    .filter(([, session]) => ACTIVE_ACTIONS.has(session.action))
    .map(([sessionId]) => sessionId);
}

export function resolveFollowTarget(
  sessions: PetSessionState,
  follow: PetFollowOptions,
): string | null {
  const entries = Object.keys(sessions);
  if (entries.length === 0) return null;

  const pinned =
    follow.mode === 'pinned' && follow.pinnedSessionId && sessions[follow.pinnedSessionId]
      ? follow.pinnedSessionId
      : null;
  if (pinned) return pinned;

  const focus =
    follow.focusSessionId && sessions[follow.focusSessionId] ? follow.focusSessionId : null;
  const focusLive = focus ? ACTIVE_ACTIONS.has(sessions[focus]!.action) : false;
  // Focus mode (and a pinned pet whose target vanished) prefers the focused
  // session while it is live; urgent mode always bubbles up the most urgent.
  if (follow.mode !== 'urgent' && focus && focusLive) return focus;

  const live = liveSessionIds(sessions)[0];
  if (live) return live;
  if (focus) return focus;

  const sorted = sortedEntries(sessions);
  return sorted[0]?.[0] ?? null;
}

export function nextInCycle(ids: readonly string[], currentId: string | null): string | null {
  if (ids.length === 0) return null;
  const index = currentId ? ids.indexOf(currentId) : -1;
  return ids[(index + 1) % ids.length] ?? null;
}
