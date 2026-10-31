/**
 * Map Task Center entries to the compact report the pet main process expects.
 */

import type { PetTaskReportBridge } from '../../shared/types/electron-api';

import type { TaskCenterEntry } from './taskCenterStore';

const OMITTED = new Set(['succeeded', 'cancelled']);

export function toPetTaskReports(
  tasks: Record<string, TaskCenterEntry>,
  limit = 20,
): PetTaskReportBridge[] {
  return Object.values(tasks)
    .filter((task) => !OMITTED.has(task.status))
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, limit)
    .map((task) => ({
      id: task.id,
      kind: task.kind,
      title: task.title,
      status: task.status,
      phase: task.phase ?? null,
      percent: task.percent ?? null,
      sessionId: task.sessionId ?? null,
      runId: task.runId ?? null,
      error: task.error ?? null,
      startedAt: task.startedAt,
      finishedAt: task.finishedAt ?? null,
    }));
}
